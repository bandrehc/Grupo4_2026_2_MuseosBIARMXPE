"""CLI autónomo de las fases 1 y 2 (preparación, idioma y sentimiento). Se puede detener y reanudar."""
import argparse
import importlib.metadata
import importlib.util
import json
import os
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

from common import (DATA_ROOT,LOG_ROOT,VERSION,Progress,ProcessLock,connect,meta_get,meta_set,
                    atomic_json,utcnow,digest,REPO)
from dataset import prepare,export
from validate import validate


def parser():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['fase1','piloto','completo','exportar','detener','estado'])
    ap.add_argument('--modo',choices=['piloto','completo'],default='completo')
    ap.add_argument('--threads',type=int,default=6)
    ap.add_argument('--batch-size',type=int,default=32)
    return ap


def run(args):
    mode='piloto' if args.command=='piloto' else args.modo
    folder=DATA_ROOT/mode; folder.mkdir(parents=True,exist_ok=True)
    stop_path=folder/'stop.request'
    if args.command=='detener':
        atomic_json(stop_path,dict(requested=utcnow()))
        print('Parada solicitada. Python terminará el lote actual y conservará el checkpoint.'); return
    if args.command=='estado':
        path=LOG_ROOT/mode/'progreso.json'
        print(path.read_text(encoding='utf-8') if path.exists() else 'Sin corrida'); return
    lock=ProcessLock(folder/'process.lock')
    progress=Progress(mode)
    # Una reanudación explícita invalida la solicitud anterior, sin borrar archivos.
    stop_baseline=stop_path.stat().st_mtime_ns if stop_path.exists() else 0
    interrupted=threading.Event()
    def requested():
        return interrupted.is_set() or (stop_path.exists() and stop_path.stat().st_mtime_ns>stop_baseline)
    def handler(signum,frame): interrupted.set()
    signal.signal(signal.SIGINT,handler)
    if hasattr(signal,'SIGTERM'): signal.signal(signal.SIGTERM,handler)
    cx=None
    try:
        cx=connect(folder/'checkpoint.sqlite')
        progress.update('inicio',0,0,'Fuentes nacionales preservadas; no se ejecuta scraping')
        if args.command=='exportar':
            report=export(cx,folder/'final',progress)
        else:
            manifest=prepare(cx,mode,progress,requested)
            if manifest is None or requested():
                progress.update(message='Parada segura, datos confirmados en SQLite',estado='DETENIDO'); return
            if args.command=='fase1':
                report=export(cx,folder/'final',progress,allow_pending=True)
                validate(folder/'final',allow_pending=True)
                progress.update('fase1_completa',report['counts']['reviews'],report['counts']['reviews'],
                                'NLP todavía pendiente; estos CSV no son el cierre de fase 2',estado='FASE1_COMPLETA')
                return
            from nlp import load_models,evaluate,infer
            from topics import fit_and_assign
            models,model_errors=load_models(progress,args.threads,args.batch_size)
            if mode=='piloto':
                references=DATA_ROOT/'evaluacion_referencias.json'
                if not references.is_file(): raise FileNotFoundError('Falta evaluación textual revisada antes del piloto.')
                selected,evaluation=evaluate(references,models,folder/'evaluacion_sentimiento.json',progress)
                meta_set(cx,'sentiment_selected',selected); cx.commit()
            else:
                evaluation_path=DATA_ROOT/'piloto/evaluacion_sentimiento.json'
                pilot_report=DATA_ROOT/'piloto/final/validacion_final.json'
                if not evaluation_path.exists() or not pilot_report.exists():
                    raise ValueError('Primero debe terminar el piloto evaluado y validado; no se autoriza una corrida ciega')
                evaluation=json.loads(evaluation_path.read_text(encoding='utf-8'))
                pilot=json.loads(pilot_report.read_text(encoding='utf-8'))
                if evaluation['estado']!='APROBADO_PRELIMINAR' or pilot['estado']!='EXPORTADO' or pilot.get('validacion_independiente',{}).get('estado')!='VALIDADO':
                    raise ValueError('El piloto no aprobó todas sus etapas')
                if pilot['sources'] != manifest or pilot['version'] != VERSION:
                    raise ValueError('El piloto no corresponde a estas fuentes/versiones. Repetir piloto antes de continuar.')
                selected=evaluation['selected']
                if selected not in models: raise ValueError('El modelo elegido en el piloto no está disponible. Reevaluar, no cambiarlo silenciosamente.')
            models={name:model for name,model in models.items() if evaluation['models'].get(name,{}).get('passed',False)}
            configuration=dict(version=VERSION,selected=selected,models=[m.version for m in models.values()],
                               language='lingua_langdetect_v1',min_confidence=.55,max_tokens=256)
            old=meta_get(cx,'nlp_configuration')
            if old and old!=configuration: raise ValueError('Configuración NLP distinta del checkpoint. No se mezclan predicciones.')
            meta_set(cx,'nlp_configuration',configuration)
            packages={}
            for name in ['numpy','scipy','scikit-learn','onnxruntime','tokenizers','lingua-language-detector','langdetect']:
                try: packages[name]=importlib.metadata.version(name)
                except importlib.metadata.PackageNotFoundError: packages[name]='NO_INSTALADO'
            old_packages=meta_get(cx,'packages')
            if old_packages and old_packages!=packages: raise ValueError('Bibliotecas cambiaron durante una corrida. No se mezclan versiones.')
            meta_set(cx,'packages',packages); cx.commit()
            if not infer(cx,progress,requested,selected,models):
                progress.update(message='Parada segura del NLP',estado='DETENIDO'); return
            if not fit_and_assign(cx,folder/'models',progress,requested,args.threads):
                progress.update(message='Parada segura de tópicos',estado='DETENIDO'); return
            report=export(cx,folder/'final',progress)
            report['packages']=packages
            report['evaluation']=dict(estado=evaluation['estado'],selected=selected,models=evaluation['models'])
            report['model_load_errors']=model_errors
            atomic_json(folder/'final/validacion_final.json',report)
        progress.update('validar_salidas',0,4,'Lectura independiente de PK, FK, pesos y campos de origen')
        validate(folder/'final')
        progress.update('completado',report['counts']['reviews'],report['counts']['reviews'],
                        'CSV exportados y conciliados; revisar advertencias y etiquetas de tópicos',estado='COMPLETADO',
                        resenas_confirmadas=report['counts']['reviews'])
    except Exception as exc:
        if cx: cx.rollback()
        progress.update(message=str(exc),estado='ERROR',errores=1)
        traceback.print_exc()
        raise
    finally:
        progress.close()
        if cx: cx.close()
        lock.close()


if __name__=='__main__':
    run(parser().parse_args())
