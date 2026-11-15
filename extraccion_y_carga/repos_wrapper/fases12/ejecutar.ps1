[CmdletBinding()]
param([ValidateSet('piloto','completo','detener')][string]$Accion='completo',
      [ValidateRange(1,16)][int]$Threads=6)
$ErrorActionPreference='Stop'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$modo=if($Accion -eq 'piloto'){'piloto'}else{'completo'}
$statusPath=Join-Path $repoRoot "logs/preparacion_latam/$modo/progreso.json"
$python=Join-Path $repoRoot '.runtime_fases12/venv/Scripts/python.exe'
$cli=Join-Path $PSScriptRoot 'pipeline.py'
if($Accion -eq 'detener'){
    # Parada no requiere instalar bibliotecas, ni ejecutar Python.
    foreach($m in @('piloto','completo')){
        $folder=Join-Path $repoRoot "data/preparacion_latam/$m"
        if(Test-Path -LiteralPath $folder){
            $temp=Join-Path $folder 'stop.request.tmp'
            @{requested=[datetimeoffset]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $temp -Encoding utf8
            Move-Item -LiteralPath $temp -Destination (Join-Path $folder 'stop.request') -Force
        }
    }
    Write-Host "Parada solicitada a ambas corridas. Espera el estado DETENIDO en progreso.json antes de reiniciar."
    return
}
if(Test-Path -LiteralPath $statusPath){
    $s=Get-Content -LiteralPath $statusPath -Raw -Encoding utf8 | ConvertFrom-Json
    if($s.estado -eq 'EN_CURSO'){
        $proc=Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$s.pid)" -ErrorAction SilentlyContinue
        if($proc -and $proc.CommandLine -like '*fases12*pipeline.py*'){
            Write-Host "Ya está corriendo PID $($s.pid). No se abre un segundo proceso."
            return
        }
    }
}
& (Join-Path $PSScriptRoot 'preparar_entorno.ps1') | Out-Host
if(-not (Test-Path -LiteralPath $python)){throw 'No se creó el entorno Python.'}
if($Accion -eq 'completo'){
    $report=Join-Path $repoRoot 'data/preparacion_latam/piloto/final/validacion_final.json'
    $eval=Join-Path $repoRoot 'data/preparacion_latam/piloto/evaluacion_sentimiento.json'
    if(-not (Test-Path -LiteralPath $report) -or -not (Test-Path -LiteralPath $eval)){
        throw 'Primero ejecuta el piloto (ejecutar.ps1 -Accion piloto). La corrida completa exige un piloto aprobado.'
    }
    if((Get-Content -LiteralPath $eval -Raw -Encoding utf8|ConvertFrom-Json).estado -ne 'APROBADO_PRELIMINAR' -or
       (Get-Content -LiteralPath $report -Raw -Encoding utf8|ConvertFrom-Json).estado -ne 'EXPORTADO'){
        throw 'El piloto no aprobó. No se lanza NLP masivo con una prueba fallida.'
    }
}else{
    & $python -X utf8 $cli fase1 --modo piloto
    if($LASTEXITCODE -ne 0){throw 'Falló la preparación del piloto.'}
    & $python -X utf8 (Join-Path $PSScriptRoot 'preparar_evaluacion.py')
    if($LASTEXITCODE -ne 0){throw 'Falló la preparación de las referencias reales.'}
}
$logFolder=Join-Path $repoRoot "logs/preparacion_latam/$modo"
New-Item -ItemType Directory -Path $logFolder -Force | Out-Null
$argsList=@('-X','utf8',('"'+$cli+'"'),$Accion,'--threads',"$Threads")
$job=Start-Process -FilePath $python -ArgumentList $argsList -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logFolder 'stdout.log') -RedirectStandardError (Join-Path $logFolder 'stderr.log')
Write-Host "Proceso independiente iniciado: PID $($job.Id). Avance en $statusPath"
Write-Host 'Para una parada segura: ejecutar.ps1 -Accion detener.'
