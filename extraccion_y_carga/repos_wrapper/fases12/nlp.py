"""Inferencia reanudable sobre texto único, con estados explícitos."""
import json
import time
from collections import Counter

from common import meta_get,meta_set,atomic_json,utcnow
from models import LanguageDetector,OnnxSentiment,MODEL_SPECS


def load_models(progress,threads=6,batch_size=32):
    models={}; errors={}
    for name in MODEL_SPECS:
        try:
            progress.update('cargar_modelo',0,0,name)
            models[name]=OnnxSentiment(name,threads,batch_size,progress=progress)
        except Exception as exc:
            errors[name]=str(exc)
            progress.update('fallback_modelo',0,0,f'{name} no disponible; se intenta el otro modelo')
    if not models: raise RuntimeError(f'Ningún clasificador disponible: {errors}')
    return models,errors


def evaluate(references,models,output_path,progress):
    """Referencia preliminar de etiquetas de texto, sin usar las estrellas como etiquetas."""
    from sklearn.metrics import f1_score,recall_score,accuracy_score
    reference=json.loads(references.read_text(encoding='utf-8'))
    items=[r for r in reference if r.get('etiqueta') in ('NEGATIVO','NEUTRO','POSITIVO')]
    if len(items)<30: raise ValueError('Se necesitan al menos 30 referencias textuales revisadas antes de la corrida completa')
    results={}; details=[]
    for name,model in models.items():
        progress.update('evaluar_sentimiento',0,len(items),name)
        started=time.monotonic()
        predictions=model.predict([r['texto'] for r in items])
        seconds=time.monotonic()-started
        expected=[r['etiqueta'] for r in items]; observed=[r['sentiment'] for r in predictions]
        metrics=dict(macro_f1=float(f1_score(expected,observed,labels=['NEGATIVO','NEUTRO','POSITIVO'],average='macro',zero_division=0)),
                     accuracy=float(accuracy_score(expected,observed)),
                     recall_negativo=float(recall_score(expected,observed,labels=['NEGATIVO'],average='macro',zero_division=0)),
                     cobertura=sum(r!='NO_CLASIFICADO' for r in observed)/len(observed),
                     texts_per_second=len(items)/max(seconds,.001),seconds=seconds)
        metrics['passed']=metrics['macro_f1']>=.65 and metrics['recall_negativo']>=.70 and metrics['cobertura']>=.80
        results[name]=metrics
        details += [dict(id_review=row['id_review'],esperado=row['etiqueta'],modelo=name,**pred)
                    for row,pred in zip(items,predictions)]
    passing=[name for name,result in results.items() if result['passed']]
    if passing:
        best=max(results[name]['macro_f1'] for name in passing)
        comparable=[name for name in passing if results[name]['macro_f1']>=best-.02]
        selected=max(comparable,key=lambda name:results[name]['texts_per_second'])
    else: selected=None
    report=dict(estado='APROBADO_PRELIMINAR' if selected else 'NO_APROBADO',selected=selected,
                referencias=len(items),referencia='Etiquetas de texto revisadas por agente IA; no validación humana independiente',
                thresholds=dict(macro_f1=.65,recall_negativo=.70,cobertura=.80),models=results,details=details,
                limitations=['Muestra pequeña seleccionada; no estima exactitud poblacional.',
                              'Revisión independiente del equipo pendiente. No se usó rating para asignar etiquetas.'])
    atomic_json(output_path,report)
    if not selected: raise ValueError(f'Ningún modelo aprobó la evaluación preliminar. Resultados: {results}')
    progress.update('evaluacion_aprobada',len(items),len(items),f'{selected}; aprobación preliminar, no validación poblacional')
    return selected,report


def infer(cx,progress,stop_requested,selected,models):
    total=cx.execute('SELECT COUNT(*) FROM texts').fetchone()[0]
    done=cx.execute('SELECT COUNT(*) FROM texts WHERE nlp_status IS NOT NULL').fetchone()[0]
    detector=LanguageDetector()
    previous_engines={row[0] for row in cx.execute('SELECT DISTINCT language_engine FROM texts WHERE language_engine IS NOT NULL')}
    if previous_engines and previous_engines!={detector.engine}:
        raise ValueError('Detector de idioma cambió desde el último checkpoint. No se mezclan métodos en la corrida.')
    started=time.monotonic(); initial_done=done
    meta_set(cx,'sentiment_models',[m.manifest for m in models.values()]); cx.commit()
    while True:
        batch=cx.execute('SELECT text_hash,text FROM texts WHERE nlp_status IS NULL LIMIT 256').fetchall()
        if not batch: break
        groups={}; prepared=[]
        for row in batch:
            text=row['text']
            language,confidence,engine=detector.detect(text)
            item=dict(hash=row['text_hash'],text=text,language=language,language_score=confidence,language_engine=engine)
            if not text:
                item.update(status='SIN_TEXTO',sentiment='SIN_TEXTO')
            elif sum(c.isalpha() for c in text)<3:
                item.update(status='SIN_SENAL',sentiment='NO_CLASIFICADO')
            else:
                choices=[selected]+[m for m in models if m!=selected]
                name=next((m for m in choices if m in models and (language in models[m].supported or language=='xx')),None)
                if name is None:
                    item.update(status='IDIOMA_NO_SOPORTADO',sentiment='NO_CLASIFICADO')
                else:
                    groups.setdefault(name,[]).append(item)
            prepared.append(item)
        for name,items in groups.items():
            predictions=models[name].predict([item['text'] for item in items])
            for item,pred in zip(items,predictions):
                item.update(pred)
                item['model']=models[name].version
                item['status']=('BAJA_CONFIANZA' if pred['sentiment']=='NO_CLASIFICADO' else
                                'OK_IDIOMA_INCIERTO' if item['language']=='xx' else 'OK')
        for item in prepared:
            pn,pz,pp=item.get('probabilities',[None,None,None])
            cx.execute('''UPDATE texts SET language=?,language_score=?,language_engine=?,sentiment=?,
              sentiment_score=?,confidence=?,p_negative=?,p_neutral=?,p_positive=?,sentiment_model=?,
              tokens=?,chunks=?,nlp_status=? WHERE text_hash=?''',
              (item['language'],item['language_score'],item['language_engine'],item['sentiment'],
               item.get('score'),item.get('confidence'),pn,pz,pp,item.get('model'),
               item.get('tokens',0),item.get('chunks',0),item['status'],item['hash']))
        cx.commit(); done+=len(batch)
        speed=(done-initial_done)/max(.01,time.monotonic()-started)
        progress.update('nlp_textos_unicos',done,total,f'{speed:.1f} textos/s; lote confirmado',
                        velocidad_textos_s=round(speed,2),ultimo_checkpoint=utcnow(),
                        unidad='textos unicos',
                        resenas_confirmadas=cx.execute('SELECT COUNT(*) FROM reviews').fetchone()[0])
        if stop_requested(): return False
    meta_set(cx,'phase2_sentiment_done',True); cx.commit()
    return True
