[CmdletBinding()]
param(
    [string]$Version = "0.1.1",
    [string]$EntryPoint,
    [string]$AppName = "Local Dictation",
    [string]$AppExeName = "LocalDictationTray.exe",
    [string]$ModelRepository = "Systran/faster-whisper-base",
    [string]$ModelDirectory,
    [string]$InnoCompiler,
    [switch]$Offline,
    [switch]$SkipSelfCheck
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$buildRoot = Join-Path $projectRoot ".build"
$distRoot = Join-Path $projectRoot "dist"
$distDir = Join-Path $distRoot "LocalDictationTray"
$installerOutput = Join-Path $projectRoot "dist-installer"
$modelRoot = if ($ModelDirectory) { $ModelDirectory } else { Join-Path $projectRoot "assets\models\faster-whisper-base" }
$iconPath = Join-Path $projectRoot "assets\tray-icon.ico"

function Find-Python {
    $candidates = @(@("py", "-3.12"), @("py", "-3.11"), @("python", ""))
    foreach ($candidate in $candidates) {
        try {
            if ($candidate[1]) { $versionOutput = & $candidate[0] $candidate[1] --version 2>&1 } else { $versionOutput = & $candidate[0] --version 2>&1 }
            if (($LASTEXITCODE -eq 0) -and ($versionOutput -match "Python (3\.(11|12))\.")) {
                return [PSCustomObject]@{ Command = $candidate[0]; Argument = $candidate[1]; Version = $Matches[1] }
            }
        } catch { }
    }
    throw "Python 3.11 or 3.12 is required on the build machine."
}

function Find-InnoCompiler {
    param([string]$RequestedPath)
    $candidates = @($RequestedPath)
    if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe") }
    if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe") }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    throw "Inno Setup 6 ISCC.exe was not found. Pass -InnoCompiler or install it on the build machine."
}

if (-not $EntryPoint) { $EntryPoint = Join-Path $projectRoot "main.py" }
if (-not (Test-Path -LiteralPath $EntryPoint -PathType Leaf)) { throw "Entry point not found: $EntryPoint" }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "requirements.txt") -PathType Leaf)) { throw "requirements.txt was not found." }
if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) { throw "Application icon was not found: $iconPath" }

$python = Find-Python
$venvPath = Join-Path $buildRoot ("packaging-venv-" + $python.Version)
$venvPython = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    if ($python.Argument) { & $python.Command $python.Argument -m venv $venvPath } else { & $python.Command -m venv $venvPath }
    if ($LASTEXITCODE -ne 0) { throw "Could not create the isolated build environment." }
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $venvPython -m pip install -r (Join-Path $projectRoot "requirements.txt") "huggingface_hub>=0.25,<1"
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

if (-not (Test-Path -LiteralPath (Join-Path $modelRoot "model.bin") -PathType Leaf)) {
    if ($Offline) { throw "Offline build requires a prepared model directory: $modelRoot" }
    New-Item -ItemType Directory -Force -Path $modelRoot | Out-Null
    $modelRepoForPython = $ModelRepository.Replace("'", "\\'")
    $modelPathForPython = $modelRoot.Replace("'", "\\'")
    & $venvPython -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='$modelRepoForPython', local_dir=r'$modelPathForPython')"
    if ($LASTEXITCODE -ne 0) { throw "Could not download model $ModelRepository" }
}

foreach ($file in @("config.json", "model.bin", "tokenizer.json")) {
    if (-not (Test-Path -LiteralPath (Join-Path $modelRoot $file) -PathType Leaf)) { throw "Incomplete model; missing ${file} in $modelRoot" }
}

New-Item -ItemType Directory -Force -Path $distRoot, $installerOutput | Out-Null
$hookPath = Join-Path $projectRoot "packaging\hooks\runtime_local_dictation.py"
$pyInstallerArgs = @(
    "--noconfirm", "--clean", "--onedir", "--windowed", "--name", "LocalDictationTray",
    "--distpath", $distRoot, "--workpath", (Join-Path $buildRoot "pyinstaller-work"),
    "--specpath", (Join-Path $buildRoot "pyinstaller-spec"), "--paths", $projectRoot,
    "--runtime-hook", $hookPath, "--add-data", "$modelRoot;models\faster-whisper-base",
    "--add-data", "$iconPath;assets", "--icon", $iconPath,
    "--collect-all", "faster_whisper", "--collect-all", "ctranslate2", "--collect-all", "av",
    "--collect-all", "PySide6", "--hidden-import", "sounddevice", "--hidden-import", "keyboard",
    "--hidden-import", "pyperclip", $EntryPoint
)
& $venvPython -m PyInstaller @pyInstallerArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with code $LASTEXITCODE" }

& (Join-Path $PSScriptRoot "test-package.ps1") -DistDir $distDir -AppExeName $AppExeName -RunSelfCheck:(-not $SkipSelfCheck)

$iscc = Find-InnoCompiler $InnoCompiler
$issPath = Join-Path $projectRoot "packaging\installer.iss"
$baseName = "LocalDictationTray-$Version-Setup"
& $iscc "/DAppName=$AppName" "/DAppVersion=$Version" "/DAppExeName=$AppExeName" "/DSourceDir=$distDir" "/DOutputDir=$installerOutput" "/DOutputBaseName=$baseName" "/DIconFile=$iconPath" $issPath
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with code $LASTEXITCODE" }

$installer = Join-Path $installerOutput "$baseName.exe"
& (Join-Path $PSScriptRoot "test-installer.ps1") -InstallerPath $installer
Get-FileHash -Algorithm SHA256 -LiteralPath $installer
Write-Host "Installer created: $installer"
