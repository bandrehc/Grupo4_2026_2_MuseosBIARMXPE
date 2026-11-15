param([switch]$Piloto)
$ErrorActionPreference='Stop'
$taskPrivate=Join-Path $env:LOCALAPPDATA 'MuseosLatamSQL'
$taskPython=Join-Path $taskPrivate 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Preparar el entorno aislado según README.md' }
if (Test-Path -LiteralPath (Join-Path $taskPrivate 'stop.request')) { Remove-Item -LiteralPath (Join-Path $taskPrivate 'stop.request') }
$taskMode=if ($Piloto) {'--piloto'} else {'--completo'}
& $taskPython (Join-Path $PSScriptRoot 'cargar.py') $taskMode
if ($LASTEXITCODE -ne 0) { throw 'Carga detenida. Revisar %LOCALAPPDATA%\MuseosLatamSQL\ultimo_error.log' }
