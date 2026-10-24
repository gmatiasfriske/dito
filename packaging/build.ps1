param(
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$pyinstaller = Join-Path $root ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $pyinstaller)) {
    throw "PyInstaller nao encontrado em $pyinstaller"
}

$dist = Join-Path $root "dist"
$recorderDist = Join-Path $dist "recorder"
$build = Join-Path $root "build"

if (-not $NoClean) {
    if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
    if (Test-Path $build) { Remove-Item $build -Recurse -Force }
}
New-Item -ItemType Directory -Force -Path $recorderDist | Out-Null

$oldErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $pyinstaller --noconfirm --clean `
    --distpath $recorderDist `
    --workpath (Join-Path $build "recorder") `
    (Join-Path $PSScriptRoot "mic_recorder.spec")
$recorderCode = $LASTEXITCODE
if ($recorderCode -ne 0) {
    $ErrorActionPreference = $oldErrorAction
    throw "Falha ao empacotar mic_recorder.exe (exit $recorderCode)"
}

& $pyinstaller --noconfirm --clean `
    --distpath $dist `
    --workpath (Join-Path $build "main") `
    (Join-Path $PSScriptRoot "Dito.spec")
$mainCode = $LASTEXITCODE
$ErrorActionPreference = $oldErrorAction
if ($mainCode -ne 0) {
    throw "Falha ao empacotar Dito.exe (exit $mainCode)"
}

$appDir = Join-Path $dist "Dito"
Copy-Item (Join-Path $recorderDist "mic_recorder.exe") `
    (Join-Path $appDir "mic_recorder.exe") -Force
Copy-Item (Join-Path $root "README.md") $appDir -Force
Copy-Item (Join-Path $root "LICENSE") $appDir -Force

$hash = Get-FileHash (Join-Path $appDir "Dito.exe") -Algorithm SHA256
"$($hash.Hash)  Dito.exe" | Set-Content (Join-Path $appDir "SHA256.txt") -Encoding ASCII

Write-Host ""
Write-Host "Pacote pronto: $appDir"
Write-Host "SHA256: $($hash.Hash)"
