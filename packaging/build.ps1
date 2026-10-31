param([switch]$Lite)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "venv not found: $Python"
}

Write-Host "== PyInstaller =="
& $Python -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "RoseSI.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$Dist = Join-Path $Root "dist\RoseSI"
if (-not (Test-Path (Join-Path $Dist "RoseSI.exe"))) {
    throw "missing built exe"
}

Write-Host "== bundled models =="
$PrepArgs = @((Join-Path $PSScriptRoot "prepare_models.py"), $Dist)
if ($Lite) { $PrepArgs += "--lite" }
& $Python @PrepArgs
if ($LASTEXITCODE -ne 0) { throw "prepare_models failed" }

Write-Host "== docs / extension =="
$ExtDst = Join-Path $Dist "extension"
$LicDst = Join-Path $Dist "LICENSES"
if (Test-Path $ExtDst) { Remove-Item -Recurse -Force $ExtDst }
if (Test-Path $LicDst) { Remove-Item -Recurse -Force $LicDst }
Copy-Item -Recurse -Force (Join-Path $Root "extension") $ExtDst
Copy-Item -Force (Join-Path $Root "README.md") $Dist
Copy-Item -Force (Join-Path $Root "THIRD_PARTY_NOTICES.md") $Dist
if ($Lite) {
    Copy-Item -Force (Join-Path $PSScriptRoot "models-lite.json") (Join-Path $Dist "models.json")
} else {
    Copy-Item -Force (Join-Path $PSScriptRoot "models.json") $Dist
}
Copy-Item -Recurse -Force (Join-Path $Root "LICENSES") $LicDst

$PortableReadme = if ($Lite) { "PORTABLE_README_LITE.txt" } else { "PORTABLE_README.txt" }
Copy-Item -Force (Join-Path $PSScriptRoot $PortableReadme) (Join-Path $Dist "PORTABLE-README.txt")

Write-Host "== done =="
Write-Host $Dist
Get-ChildItem $Dist | Select-Object Name, Length
exit 0
