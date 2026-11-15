param([switch]$SoloPilotos)
$ErrorActionPreference='Stop'
function Get-TaskSha([string]$File){$stream=[System.IO.File]::OpenRead($File);$algorithm=[System.Security.Cryptography.SHA256]::Create();try{[BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','')}finally{$stream.Dispose();$algorithm.Dispose()}}
$root=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python=Join-Path $env:USERPROFILE '.museos_runtime/topicos/venv/Scripts/python.exe'
$control=Join-Path $root 'data/preparacion_latam/completo/comparacion_topicos/stop.request'
$stamp=if(Test-Path -LiteralPath $control){(Get-Item -LiteralPath $control).LastWriteTimeUtc.Ticks}else{0}
$steps=@(@('LDA','--pilot'),@('S-BERT','--pilot'))
if(-not $SoloPilotos){$steps+=@(@('LDA'),@('S-BERT'))}
foreach($step in $steps){
  if((Test-Path -LiteralPath $control) -and (Get-Item -LiteralPath $control).LastWriteTimeUtc.Ticks -gt $stamp){exit 130}
  $mode=if($step.Count -gt 1){'piloto'}else{'completo'}
  $folder=if($mode -eq 'piloto'){Join-Path $root ('data/preparacion_latam/completo/comparacion_topicos/piloto/'+$step[0]+'/salidas')}else{Join-Path $root ('data/preparacion_latam/completo/final/'+$step)}
  $reportPath=Join-Path $folder 'validacion_final.json'
  $completed=$false
  if(Test-Path -LiteralPath $reportPath){
    $report=Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $completed=$report.estado -eq 'EXPORTADO' -and $report.validacion_independiente.estado -eq 'VALIDADO'
    if($step[0] -eq 'S-BERT' -or $step -eq 'S-BERT'){if($report.modelo_topicos.clustering_schema -ne 'differential-v2'){$completed=$false}}
    if($completed){foreach($output in $report.outputs){$path=Join-Path $folder $output.file;if(-not(Test-Path -LiteralPath $path) -or (Get-TaskSha $path) -ne $output.sha256){$completed=$false;break}}}
  }
  if($completed){Write-Host "Reutilizando $mode $($step): export validado y hashes conciliados.";continue}
  & $python -X utf8 (Join-Path $PSScriptRoot 'experiment.py') @step
  if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
}
if(-not $SoloPilotos){
  & $python -X utf8 (Join-Path $PSScriptRoot 'comparar.py')
  exit $LASTEXITCODE
}
