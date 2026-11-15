param([switch]$SoloPilotos)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python=& (Join-Path $PSScriptRoot 'preparar_entorno.ps1')
$python=@($python)[-1]
$log=Join-Path $root 'logs/preparacion_latam/topicos_comparacion'
New-Item -ItemType Directory -Path $log -Force | Out-Null
$active=Get-CimInstance Win32_Process | Where-Object {$_.Name -like 'python*' -and $_.CommandLine -match 'topicos_comparacion[\\/]experiment.py'}
if($active){Write-Host 'Ya hay un experimento activo.'}
else {
  $argsList=@('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+(Join-Path $PSScriptRoot 'secuencia.ps1')+'"'))
  if($SoloPilotos){$argsList+='-SoloPilotos'}
  Start-Process powershell.exe -WindowStyle Hidden -ArgumentList $argsList -WorkingDirectory $root -RedirectStandardOutput (Join-Path $log 'secuencia.stdout.log') -RedirectStandardError (Join-Path $log 'secuencia.stderr.log') | Out-Null
  Write-Host "Experimento iniciado; registros en $log"
}
