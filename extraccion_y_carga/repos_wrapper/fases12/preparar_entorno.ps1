[CmdletBinding()]
param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtimeRoot = Join-Path $repoRoot '.runtime_fases12'
$venvPython = Join-Path $runtimeRoot 'venv/Scripts/python.exe'
$requirements = Join-Path $PSScriptRoot 'requirements.txt'

function Test-TaskPython([string]$Candidate) {
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate)) { return $false }
    $version = & $Candidate -c 'import sys; print("%s.%s" % sys.version_info[:2])' 2>$null
    return $LASTEXITCODE -eq 0 -and $version -in @('3.12','3.13')
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    $candidates = @($Python)
    foreach ($version in @('3.12','3.13')) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $candidate = & py "-$version" -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0) { $candidates += $candidate }
        }
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $selected = $candidates | Where-Object { Test-TaskPython $_ } | Select-Object -First 1
    if (-not $selected) {
        Write-Host 'No hay Python 3.12-3.13. Intentando instalar Python 3.13 solo para este usuario...'
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw 'Instala Python 3.12 o 3.13 para tu usuario desde https://www.python.org/downloads/windows/ y vuelve a ejecutar.'
        }
        & winget install --id Python.Python.3.13 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo instalar Python sin administrador. Instala Python para tu usuario y reintenta.' }
        $selected = Join-Path $env:LOCALAPPDATA 'Programs/Python/Python313/python.exe'
        if (-not (Test-TaskPython $selected)) { throw 'Python instalado no se encontro. Abre otra terminal y reintenta.' }
    }
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    Write-Host "Creando entorno aislado: $runtimeRoot"
    & $selected -m venv (Join-Path $runtimeRoot 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Fallo al crear el entorno virtual.' }
}

$installStamp = Join-Path $runtimeRoot 'requirements.sha256'
$requiredHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
$installed = (Test-Path -LiteralPath $installStamp) -and (Get-Content -LiteralPath $installStamp -Raw).Trim() -eq $requiredHash
if (-not $installed) {
    Write-Host 'Instalando dependencias. No se modifica el Python global ni se requieren permisos de administrador.'
    $coreRequirements=Join-Path $runtimeRoot 'requirements_core.txt'
    Get-Content -LiteralPath $requirements | Where-Object {$_ -notmatch '^lingua-language-detector'} | Set-Content -LiteralPath $coreRequirements -Encoding utf8
    & $venvPython -m pip install --disable-pip-version-check --retries 3 --timeout 60 -r $coreRequirements
    if ($LASTEXITCODE -ne 0) { throw 'Instalacion incompleta: revisa conexion. Puedes ejecutar de nuevo sin perder datos.' }
    & $venvPython -m pip install --disable-pip-version-check --retries 3 --timeout 60 'lingua-language-detector==2.2.0'
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Lingua no disponible. Se usara langdetect con semilla fija; quedara registrado por texto.' }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Hay dependencias incompatibles.' }
    Set-Content -LiteralPath $installStamp -Value $requiredHash -Encoding utf8
}
Write-Host "Entorno preparado: $venvPython"
Write-Output $venvPython
