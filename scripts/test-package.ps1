[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$DistDir,
    [string]$AppExeName = "LocalDictationTray.exe",
    [switch]$RunSelfCheck,
    [switch]$RunGpuSelfCheck
)

$ErrorActionPreference = "Stop"
$resolvedDistDir = (Resolve-Path -LiteralPath $DistDir).Path
$exePath = Join-Path $resolvedDistDir $AppExeName

if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "Не найдено приложение в пакете: $exePath"
}

$signature = [System.IO.File]::ReadAllBytes($exePath)[0..1]
if (($signature[0] -ne 0x4D) -or ($signature[1] -ne 0x5A)) {
    throw "Файл не является Windows PE executable: $exePath"
}

$modelCandidates = @(
    (Join-Path $resolvedDistDir "_internal\\models\\faster-whisper-small"),
    (Join-Path $resolvedDistDir "models\\faster-whisper-small")
)
$modelDir = $modelCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Container } | Select-Object -First 1
if (-not $modelDir) {
    throw "Bundled faster-whisper model directory was not found under $resolvedDistDir"
}

$cudaDlls = @("cublas64_12.dll", "cudnn64_8.dll")
foreach ($dll in $cudaDlls) {
    $found = Get-ChildItem -Path $resolvedDistDir -Recurse -Filter $dll -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $found) { throw "Bundled NVIDIA CUDA runtime is missing $dll" }
}
$requiredModelFiles = @("config.json", "model.bin", "tokenizer.json")
foreach ($file in $requiredModelFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $modelDir $file) -PathType Leaf)) {
        throw "В дистрибутиве нет локальной модели faster-whisper: $file"
    }
}

if ($RunGpuSelfCheck) {
    $gpuCheck = Start-Process -FilePath $exePath -ArgumentList "--gpu-self-check" -Wait -PassThru
    if ($gpuCheck.ExitCode -ne 0) { throw "GPU self-check failed with code $($gpuCheck.ExitCode)" }
}

if ($RunSelfCheck) {
    # Windowed PyInstaller applications are detached by direct PowerShell invocation.
    # Wait for the real process and retain its exit status for the existing assertion.
    $selfCheck = Start-Process -FilePath $exePath -ArgumentList "--self-check" -Wait -PassThru
    $LASTEXITCODE = $selfCheck.ExitCode
    if ($LASTEXITCODE -ne 0) { throw "Self-check приложения завершился с кодом $LASTEXITCODE" }
}

Write-Host "Пакет корректен: $resolvedDistDir"
