"""Comparación sobre los mismos textos fuera del entrenamiento; no inventa exactitud."""
import csv
import argparse
import json
import math
from collections import Counter
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from experiment import FINAL,WORK,ro_source,connection,meta_get,read_csv,save_csv,atomic_json,utcnow,model_key,assignment_table,Progress

def npmi(texts,terms):
    vocabulary=sorted({w for group in terms for w in group[:10]})
    vector=CountVectorizer(vocabulary=vocabulary,ngram_range=(1,2),strip_accents='unicode')
    matrix=(vector.transform(texts)>0).astype(np.int32)
    index=vector.vocabulary_; n=len(texts); scores=[]
    for group in terms:
        cols=[index[w] for w in group[:10]]
        binary=matrix[:,cols].toarray(); df=binary.sum(axis=0); pairs=binary.T@binary
        for i in range(len(cols)):
            for j in range(i+1,len(cols)):
                if pairs[i,j]==0: scores.append(-1.); continue
                pij=(pairs[i,j]+.5)/(n+1); pi=(df[i]+.5)/(n+1); pj=(df[j]+.5)/(n+1)
                scores.append(math.log(pij/(pi*pj))/-math.log(pij))
    return float(np.mean(scores)) if scores else -1.

def compare(pilot=False):
    source=ro_source(); connections={}; manifests={}
    progress=Progress('topicos_comparacion') if not pilot else None
    try:
        if progress: progress.update('comparacion_validar',0,2,'Validar títulos, columnas conservadas y las dos salidas nuevas')
        for method in ('LDA','S-BERT'):
            if not pilot:
                from etiquetar import apply
                apply(method)
            folder=WORK/'piloto'/method/'salidas' if pilot else FINAL/method
            report_path=folder/'validacion_final.json'
            if not report_path.exists(): raise ValueError('Todavía falta completar '+method)
            report=json.loads(report_path.read_text(encoding='utf8'))
            if report.get('validacion_independiente',{}).get('estado')!='VALIDADO': raise ValueError('Salida sin validar '+method)
            if not pilot:
                from verificar_conservacion import check
                check(folder)
            connections[method]=connection(WORK/('piloto' if pilot else 'completo')/method/'checkpoint.sqlite')
            manifests[method]=meta_get(connections[method],model_key(method))
            if progress: progress.update('comparacion_validar',len(manifests),2,'Integridad y conservación confirmadas: '+method)
        held=manifests['LDA']['holdout_hashes']
        if held!=manifests['S-BERT']['holdout_hashes']: raise ValueError('Las muestras de evaluación no son las mismas')
        texts=[source.execute('SELECT text FROM texts WHERE text_hash=?',(h,)).fetchone()[0] for h in held]
        records=[]; metrics=[]
        catalogs={m:[r for _,r in read_csv((WORK/'piloto'/m/'salidas' if pilot and m!='NMF' else FINAL/m)/'catalogo_dimensiones_latentes.csv')] for m in ('NMF','LDA','S-BERT')}
        for method in ('NMF','LDA','S-BERT'):
            if progress: progress.update('comparacion_metricas',len(metrics),3,'Evaluar '+method+' sobre muestra común fuera del entrenamiento')
            histogram=Counter(); assigned=0
            for h in held:
                if method=='NMF':
                    row=source.execute('SELECT topic_status,topics_json FROM texts WHERE text_hash=?',(h,)).fetchone()
                else:
                    row=connections[method].execute(f'SELECT status,weights FROM {assignment_table(method)} WHERE hash=?',(h,)).fetchone()
                if row is None: raise ValueError('Falta una evaluación '+method)
                pairs=json.loads(row[1]); dominant=max(pairs,key=lambda x:x[1])[0] if pairs else ''
                assigned+=bool(pairs); histogram[dominant]+=1
                records.append(dict(tecnica=method,hash_texto_nlp=h,estado=row[0],topico_dominante=dominant))
            terms=[r['palabras_clave'].split('; ')[:10] for r in catalogs[method]]
            diversity=len({w for g in terms for w in g})/sum(map(len,terms))
            metrics.append(dict(tecnica=method,textos_evaluacion=len(held),topicos=len(terms),textos_asignados=assigned,
                cobertura=assigned/len(held),npmi_holdout=npmi(texts,terms),diversidad_lexica=diversity,
                mayor_grupo_proporcion=max((v for k,v in histogram.items() if k),default=0)/max(1,assigned)))
        # Separación semántica en 384D, sobre EXACTAMENTE los mismos puntos asignados por los tres.
        # No usar la proyección UMAP 2D para esta métrica.
        from sklearn.metrics import silhouette_score
        assignments={m:{r['hash_texto_nlp']:r['topico_dominante'] for r in records if r['tecnica']==m} for m in ('NMF','LDA','S-BERT')}
        shared=[h for h in held if all(assignments[m][h] for m in assignments)]
        vectors=[]
        for h in shared:
            row=connections['S-BERT'].execute('SELECT vector FROM embeddings WHERE hash=?',(h,)).fetchone()
            if row is None: raise ValueError('Falta embedding de evaluación')
            vectors.append(np.frombuffer(row[0],dtype=np.float32))
        for item in metrics:
            labels=[assignments[item['tecnica']][h] for h in shared]
            item['textos_comunes_para_silueta']=len(shared)
            item['silueta_coseno_384d']=''
            if 2<=len(set(labels))<len(shared):
                item['silueta_coseno_384d']=float(silhouette_score(np.stack(vectors),labels,metric='cosine',sample_size=min(2000,len(shared)),random_state=20261011))
            groups=[set(r['palabras_clave'].split('; ')[:10]) for r in catalogs[item['tecnica']]]
            overlaps=[len(a&b)/len(a|b) for i,a in enumerate(groups) for b in groups[i+1:]]
            item['solapamiento_lexico_medio']=float(np.mean(overlaps)) if overlaps else 0.
        out=WORK/'comparacion_piloto' if pilot else FINAL/'comparacion'; out.mkdir(exist_ok=True)
        files=[save_csv(out,'comparacion_metricas.csv',list(metrics[0]),metrics),
               save_csv(out,'evaluacion_comun.csv',list(records[0]),records)]
        report=dict(fecha=utcnow(),pilot=pilot,muestra=f'{len(held)} textos únicos españoles fuera del entrenamiento.',
             metricas=metrics,outputs=files,decision='PENDIENTE_REVISION_SEMANTICA',
             advertencias=['No hay etiquetas humanas exhaustivas: NO son métricas de accuracy o F1.',
               'NMF conserva su vectorización original; LDA y S-BERT usan supresión adicional de adjetivos genéricos. Se comparan pipelines, no algoritmos aislados.',
               'HDBSCAN admite ruido/no asignados. Un solo tópico por reseña no equivale a mezcla LDA/NMF.',
               'UMAP 2D es una proyección ilustrativa; no demuestra separación en el espacio original.',
               'Silueta usa embeddings S-BERT 384D y solo intersección de textos asignados; esta representación favorece criterios semánticos, no reemplaza revisión humana.',
               'Debe revisar ejemplos, redundancia y utilidad para negocio antes de elegir un ganador.'])
        if pilot: report['advertencias'].append('PILOTO: NMF baseline entrenado con 20000 textos, LDA/S-BERT con 2000. No usar para elegir ganador; es prueba funcional del comparador.')
        atomic_json(out/'comparacion.json',report)
        if progress: progress.update('completado_comparacion',3,3,'Tres métodos comparados. Revisar títulos y utilidad antes de elegir.',estado='COMPLETADO')
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except Exception as exc:
        if progress: progress.update(message=str(exc),estado='ERROR',errores=1)
        raise
    finally:
        source.close()
        for cx in connections.values(): cx.close()
        if progress: progress.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--pilot',action='store_true'); compare(parser.parse_args().pilot)
