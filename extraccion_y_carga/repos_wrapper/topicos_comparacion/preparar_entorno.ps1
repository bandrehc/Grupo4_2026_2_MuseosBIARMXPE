[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$envRoot=Join-Path $root '.runtime_topicos'
New-Item -ItemType Directory -Path $envRoot -Force | Out-Null
$shortRuntime=Join-Path $env:USERPROFILE '.museos_runtime/topicos'
$python=Join-Path $shortRuntime 'venv/Scripts/python.exe'
if(-not(Test-Path -LiteralPath $python)){
    $base=Join-Path $root '.runtime_fases12/venv/Scripts/python.exe'
    if(-not(Test-Path -LiteralPath $base)){& (Join-Path $root 'repos_wrapper/fases12/preparar_entorno.ps1') | Out-Host}
    New-Item -ItemType Directory -Path $shortRuntime -Force | Out-Null
    & $base -m venv (Join-Path $shortRuntime 'venv')
    if($LASTEXITCODE -ne 0){throw 'No se pudo crear el entorno aislado.'}
}
$requirements=Join-Path $PSScriptRoot 'requirements.txt'
$hash=(Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
$stamp=Join-Path $envRoot 'requirements.sha256'
if(-not(Test-Path -LiteralPath $stamp) -or (Get-Content -LiteralPath $stamp -Raw).Trim() -ne $hash){
    & $python -m pip install --disable-pip-version-check --retries 3 --timeout 60 'torch==2.14.1+cpu' --index-url https://download.pytorch.org/whl/cpu | Out-Host
    if($LASTEXITCODE -ne 0){throw 'No se pudo instalar PyTorch CPU. Reintenta con internet.'}
    & $python -m pip install --disable-pip-version-check --retries 3 --timeout 60 -r $requirements | Out-Host
    if($LASTEXITCODE -ne 0){throw 'Instalacion incompleta. No se modifico el entorno anterior.'}
    & $python -m pip check | Out-Host
    if($LASTEXITCODE -ne 0){throw 'Dependencias incompatibles.'}
    Set-Content -LiteralPath $stamp -Value $hash -Encoding utf8
}
Write-Output $python
