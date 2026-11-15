"""Supervisor local secuencial y reanudable; no cambia modelos ni datos anteriores."""
from pathlib import Path
import os
import subprocess
import sys
import time
import argparse
import json

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'data/preparacion_latam/ampliacion_2026-10-22_v1'
sys.path.insert(0,str(ROOT/'repos_wrapper/fases12'))
from common import atomic_json, utcnow, ProcessLock


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reanudar',action='store_true')
    args=parser.parse_args()
    WORK.mkdir(parents=True,exist_ok=True)
    lock=ProcessLock(WORK/'supervisor.lock')
    if args.reanudar and (WORK/'stop.request').exists():
        (WORK/'stop.request').rename(WORK/f'stop.atendida.{time.time_ns()}.json')
    base=Path(sys.executable)
    sentiment=ROOT/'.runtime_fases12/venv/Scripts/python.exe'
    topics=Path(os.environ['USERPROFILE'])/'.museos_runtime/topicos/venv/Scripts/python.exe'
    script=Path(__file__).with_name('pipeline.py')
    stages=[('preparar',base,[]),('conciliar',base,[]),('exportar',base,['--parcial']),('sentimiento',sentiment,[]),('topicos',topics,[]),('exportar',base,[])]
    if args.reanudar and (WORK/'supervisor.json').exists():
        previous=json.loads((WORK/'supervisor.json').read_text(encoding='utf-8'))
        # Validar fuentes siempre, sin regenerar innecesariamente el CSV parcial.
        if previous.get('stage') in ('sentimiento','topicos'):
            index=next(i for i,s in enumerate(stages) if s[0]==previous['stage'])
            stages=[stages[0],*stages[index:]]
    try:
        for stage,python,extra in stages:
            if (WORK/'stop.request').exists():
                atomic_json(WORK/'supervisor.json',dict(state='DETENIDO',stage=stage,updated=utcnow())); return
            atomic_json(WORK/'supervisor.json',dict(state='EN_CURSO',stage=stage,pid=os.getpid(),updated=utcnow()))
            result=subprocess.run([str(python),'-u',str(script),stage,*extra],cwd=ROOT)
            if result.returncode:
                if (WORK/'stop.request').exists():
                    atomic_json(WORK/'supervisor.json',dict(state='DETENIDO',stage=stage,updated=utcnow()))
                    return
                atomic_json(WORK/'supervisor.json',dict(state='ERROR',stage=stage,exit_code=result.returncode,updated=utcnow()))
                raise SystemExit(result.returncode)
        atomic_json(WORK/'supervisor.json',dict(state='COMPLETADO_TECNICAMENTE',updated=utcnow(),human_validation='PENDIENTE'))
    finally: lock.close()


if __name__=='__main__': main()
