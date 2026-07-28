[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$InstallerPath,
    [long]$MinimumBytes = 1MB
)

$ErrorActionPreference = "Stop"
$resolvedInstaller = (Resolve-Path -LiteralPath $InstallerPath).Path

if ([System.IO.Path]::GetExtension($resolvedInstaller) -ne ".exe") {
    throw "Ожидается .exe установщик: $resolvedInstaller"
}

$installer = Get-Item -LiteralPath $resolvedInstaller
if ($installer.Length -lt $MinimumBytes) {
    throw "Установщик подозрительно мал ($($installer.Length) bytes): $resolvedInstaller"
}

$signature = [System.IO.File]::ReadAllBytes($resolvedInstaller)[0..1]
if (($signature[0] -ne 0x4D) -or ($signature[1] -ne 0x5A)) {
    throw "Файл не является Windows executable: $resolvedInstaller"
}

Write-Host "Установщик корректен: $resolvedInstaller ($([math]::Round($installer.Length / 1MB, 1)) MB)"
