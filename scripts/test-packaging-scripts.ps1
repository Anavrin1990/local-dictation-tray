[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
foreach ($relativePath in @("scripts\build-installer.ps1", "scripts\test-package.ps1", "scripts\test-installer.ps1")) {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $projectRoot $relativePath), [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) { throw "Syntax error in ${relativePath}: $($errors[0].Message)" }
}

$iss = Get-Content -LiteralPath (Join-Path $projectRoot "packaging\installer.iss") -Raw
foreach ($requiredText in @("AppId=", "Compression=lzma2/ultra64", "ArchitecturesAllowed=x64compatible", "[Files]", "recursesubdirs")) {
    if (-not $iss.Contains($requiredText)) { throw "Required installer value is missing: ${requiredText}" }
}
Write-Host "Packaging scripts are syntactically valid."
