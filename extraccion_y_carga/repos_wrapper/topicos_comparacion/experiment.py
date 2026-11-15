"""Tópicos independientes y reanudables; nunca recalcula sentimiento ni scraping."""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import random
import shutil
import signal
import sqlite3
import sys
import time
from collections import Counter,defaultdict
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fases12'))
from common import REPO,DATA_ROOT,Progress,ProcessLock,atomic_json,digest,meta_get,meta_set,read_csv,utcnow
from topics import STOPWORDS,quality
from validate import validate

FINAL=DATA_ROOT/'completo/final'
WORK=DATA_ROOT/'completo/comparacion_topicos'
MODEL_NAME='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
MODEL_REVISION='e8f8c211226b894fcb81acc59f3b34ba3efd5f42'
VERSION='comparacion-topicos-1.0'
SEED=20261011
CLUSTERING_SCHEMA='differential-v2'
def assignment_table(method): return 'assignments_v2' if method=='S-BERT' else 'assignments'
def model_key(method): return 'model_v2' if method=='S-BERT' else 'model'
# Solo representación léxica temática: conservar negaciones y texto semántico original.
GENERIC='bueno buena buenos buenas excelente excelentes bonito bonita bonitos bonitas interesante interesantes maravilloso maravillosa hermoso hermosa recomendable recomiendo visitar museo museos lugar lugares muy todo si bien super'.split()

def ro_source():
    path=DATA_ROOT/'completo/checkpoint.sqlite'
    cx=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    cx.row_factory=sqlite3.Row
    return cx

def connection(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    cx=sqlite3.connect(path,timeout=60); cx.row_factory=sqlite3.Row
    cx.execute('PRAGMA synchronous=FULL')
    cx.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS embeddings(hash TEXT PRIMARY KEY,vector BLOB NOT NULL,chunks INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS assignments(hash TEXT PRIMARY KEY,status TEXT NOT NULL,weights TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS assignments_v2(hash TEXT PRIMARY KEY,status TEXT NOT NULL,weights TEXT NOT NULL);
    ''')
    return cx

def baseline():
    report=json.loads((FINAL/'validacion_final.json').read_text(encoding='utf8'))
    if report['estado']!='EXPORTADO': raise ValueError('La base madre todavía no terminó')
    folder=FINAL/'NMF'; folder.mkdir(exist_ok=True)
    for output in report['outputs']:
        source=FINAL/output['file']; dest=folder/output['file']
        if digest(source)!=output['sha256']: raise ValueError('Fuente NMF modificada')
        if dest.exists():
            if digest(dest)!=output['sha256']: raise ValueError('La copia NMF no coincide; no se sobrescribe')
        else: shutil.copy2(source,dest)
    if not (folder/'validacion_final.json').exists(): shutil.copy2(FINAL/'validacion_final.json',folder/'validacion_final.json')
    for name in ('LDA','S-BERT'): (FINAL/name).mkdir(exist_ok=True)
    return report

def samples(source,progress,pilot=False):
    groups=defaultdict(list)
    for r in source.execute('''SELECT t.text_hash,t.text,MIN(r.country) country FROM texts t
       JOIN reviews r USING(text_hash) WHERE t.language='es' GROUP BY t.text_hash ORDER BY t.text_hash'''):
        if len(r['text'].split())>=4: groups[r['country']].append((r['text_hash'],r['text']))
    train=[]; held=[]; rng=random.Random(SEED)
    for country,items in sorted(groups.items()):
        rng.shuffle(items); train.extend(items[:10000]); held.extend(items[10000:12000])
    train.sort(); held.sort()
    fingerprint=hashlib.sha256('\n'.join(h for h,_ in train).encode()).hexdigest()
    original=meta_get(source,'topic_manifest')['models'][0]['source_hashes_sha256']
    if fingerprint!=original: raise ValueError('No se pudo reproducir exactamente el entrenamiento NMF')
    if pilot: train=train[:1000]+train[-1000:]; held=held[:250]+held[-250:]
    progress.update('muestra_comun',len(train),len(train),'Corpus compartido; prueba fuera del entrenamiento')
    return train,held,fingerprint

def eligibility(text,language):
    if not text: return 'SIN_TEXTO'
    if language not in ('es','xx'): return 'IDIOMA_FUERA_ALCANCE'
    if len(text.split())<4: return 'SIN_SENAL_TEMATICA'
    return None

def save_csv(folder,name,fields,rows):
    folder.mkdir(parents=True,exist_ok=True)
    dest=folder/name; tmp=dest.with_suffix(dest.suffix+'.tmp'); count=0
    with tmp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n'); w.writeheader()
        for row in rows: w.writerow(row); count+=1
        f.flush(); os.fsync(f.fileno())
    if count!=sum(1 for _ in read_csv(tmp)): raise ValueError('Exportación CSV no conciliada')
    tmp.replace(dest)
    return dict(file=name,rows=count,sha256=digest(dest),bytes=dest.stat().st_size)

class Embeddings:
    def __init__(self,cx,progress,stop):
        import torch
        from sentence_transformers import SentenceTransformer
        self.cx=cx; self.progress=progress; self.stop=stop
        torch.set_num_threads(6)
        torch.set_num_interop_threads(1)
        self.model=SentenceTransformer(MODEL_NAME,revision=MODEL_REVISION,
             cache_folder=str(Path(os.environ.get('USERPROFILE',str(REPO/'.runtime_topicos')))/'.museos_runtime/modelos'),
             device='cpu',trust_remote_code=False)
    def get(self,items):
        import numpy as np
        output={}; missing=[]
        for h,text in items:
            r=self.cx.execute('SELECT vector FROM embeddings WHERE hash=?',(h,)).fetchone()
            if r: output[h]=np.frombuffer(r[0],dtype=np.float32).copy()
            else: missing.append((h,text))
        for start in range(0,len(missing),64):
            if self.stop(): raise InterruptedError('Parada segura de embeddings')
            batch=missing[start:start+64]; fragments=[]; lookup=[]
            max_body=self.model.max_seq_length-2
            for h,text in batch:
                tokens=self.model.tokenizer.encode(text,add_special_tokens=False,truncation=False,verbose=False)
                for index in range(0,len(tokens),max_body):
                    body=tokens[index:index+max_body]
                    fragments.append(self.model.tokenizer.decode(body,skip_special_tokens=True))
                    lookup.append((h,len(body)))
            vectors=self.model.encode(fragments,batch_size=32,show_progress_bar=False,
                                      normalize_embeddings=True,convert_to_numpy=True)
            totals={h:np.zeros(vectors.shape[1],dtype=np.float64) for h,_ in batch}; counts=Counter(); chunks=Counter()
            for (h,n),v in zip(lookup,vectors): totals[h]+=v*n; counts[h]+=n; chunks[h]+=1
            for h,_ in batch:
                v=totals[h]/counts[h]; norm=np.linalg.norm(v)
                if not np.isfinite(v).all() or norm<=0: raise ValueError('Embedding inválido')
                v=(v/norm).astype(np.float32); output[h]=v
                self.cx.execute('INSERT INTO embeddings VALUES (?,?,?)',(h,v.tobytes(),chunks[h]))
            self.cx.commit()
            self.progress.update('embeddings_S-BERT',min(start+64,len(missing)),len(missing),
                'Vectores locales confirmados; ventanas cubren el texto completo',ultimo_checkpoint=utcnow(),unidad='textos')
        return np.stack([output[h] for h,_ in items])

def fit(method,cx,source,folder,progress,stop,pilot):
    import joblib
    import numpy as np
    from sklearn.feature_extraction.text import CountVectorizer
    from sklearn.decomposition import LatentDirichletAllocation
    from threadpoolctl import threadpool_limits
    existing=meta_get(cx,model_key(method)); model_file='model_v2.joblib' if method=='S-BERT' else 'model.joblib'
    if existing:
        if digest(folder/model_file)!=existing['sha256']: raise ValueError('Artefacto temático modificado')
        for name,version in existing.get('environment',{}).items():
            if importlib.metadata.version(name)!=version: raise ValueError('Cambió dependencia del modelo: '+name)
        return joblib.load(folder/model_file),existing,None
    train,held,corpus_hash=samples(source,progress,pilot)
    stops=sorted(set(STOPWORDS['es'])|set(GENERIC))
    vectorizer=CountVectorizer(strip_accents='unicode',stop_words=stops,ngram_range=(1,2),
                               max_features=16000,min_df=3,max_df=.85)
    texts=[t for _,t in train]; trials=[]
    if method=='LDA':
        matrix=vectorizer.fit_transform(texts); best=None
        with threadpool_limits(limits=6):
            for k in ([6,10] if pilot else [6,10,14]):
                if stop(): raise InterruptedError('Parada antes del siguiente candidato LDA')
                progress.update('entrenar_LDA',0,len(texts),f'LDA k={k}; un proceso, hasta seis hilos numéricos')
                model=LatentDirichletAllocation(n_components=k,learning_method='online',batch_size=512,
                      max_iter=6 if pilot else 10,random_state=SEED,n_jobs=1,evaluate_every=-1)
                model.fit(matrix); q=quality(matrix,model.components_); trials.append(dict(k=k,**q))
                if best is None or q['selection_score']>best[0]: best=(q['selection_score'],model)
        model=best[1]; features=vectorizer.get_feature_names_out()
        words=[[str(features[j]) for j in comp.argsort()[-12:][::-1]] for comp in model.components_]
        artifact=dict(model=model,vectorizer=vectorizer,method=method)
    else:
        from bertopic import BERTopic
        from bertopic.backend import BaseEmbedder
        from bertopic.vectorizers import ClassTfidfTransformer
        from hdbscan import HDBSCAN
        from umap import UMAP
        encoder=Embeddings(cx,progress,stop); vectors=encoder.get(train)
        progress.update('entrenar_S-BERT',0,len(train),'UMAP 5D + HDBSCAN + c-TF-IDF; no LDA combinado')
        cluster=HDBSCAN(min_cluster_size=25 if pilot else 100,min_samples=10,
             metric='euclidean',cluster_selection_method='eom',prediction_data=True,core_dist_n_jobs=6)
        reducer=UMAP(n_neighbors=20,n_components=5,min_dist=0.,metric='cosine',random_state=SEED,n_jobs=1)
        model=BERTopic(embedding_model=BaseEmbedder(),umap_model=reducer,hdbscan_model=cluster,
           vectorizer_model=vectorizer,ctfidf_model=ClassTfidfTransformer(reduce_frequent_words=True),
           calculate_probabilities=False,verbose=False)
        labels,_=model.fit_transform(texts,vectors)
        histogram=Counter(label for label in labels if label>=0)
        share=max(histogram.values(),default=0)/max(1,sum(histogram.values()))
        coarse=dict(strategy='eom',clusters=len(histogram),largest_cluster_share=share,outlier_rate=sum(x<0 for x in labels)/len(labels))
        refinement=[]
        if share>.5:
            progress.update('refinar_S-BERT',0,len(train),'Grupo demasiado amplio; probar hojas del árbol HDBSCAN sin recalcular vectores')
            leaf=HDBSCAN(min_cluster_size=25 if pilot else 100,min_samples=10,metric='euclidean',cluster_selection_method='leaf',prediction_data=True,core_dist_n_jobs=6)
            model=BERTopic(embedding_model=BaseEmbedder(),umap_model=UMAP(n_neighbors=20,n_components=5,min_dist=0.,metric='cosine',random_state=SEED,n_jobs=1),hdbscan_model=leaf,
                 vectorizer_model=CountVectorizer(**vectorizer.get_params()),ctfidf_model=ClassTfidfTransformer(reduce_frequent_words=True),calculate_probabilities=False,verbose=False)
            labels,_=model.fit_transform(texts,vectors)
            histogram=Counter(label for label in labels if label>=0)
            fine_share=max(histogram.values(),default=0)/max(1,sum(histogram.values()))
            fine_outliers=sum(x<0 for x in labels)/len(labels)
            refinement=[dict(strategy='leaf',clusters=len(histogram),largest_cluster_share=fine_share,outlier_rate=fine_outliers)]
            if fine_share>=share or fine_share>.5 or fine_outliers>.85:
                raise ValueError('No se obtuvo granularidad temática suficiente; revisar parámetros en lugar de forzar éxito')
        codes=sorted(x for x in model.get_topics() if x>=0)
        if len(codes)<2: raise ValueError('S-BERT no produjo al menos dos grupos interpretables')
        words=[[word for word,_ in model.get_topic(code)][:12] for code in codes]
        # Matriz de comparación léxica común, no reutilizar proyección 2D como métrica de calidad.
        trials=[coarse]+refinement+[dict(selected=True,clusters=len(codes),outlier_rate=sum(x<0 for x in labels)/len(labels),
                     diversity=len(set(w for topic in words for w in topic[:10]))/(10*len(words)))]
        artifact=dict(model=model,method=method,codes=codes)
        projection=UMAP(n_neighbors=20,n_components=2,min_dist=.1,metric='cosine',random_state=SEED,n_jobs=1).fit_transform(vectors)
        save_csv(folder,'proyeccion_muestra.csv',['hash_texto_nlp','x','y','cluster'],
             (dict(hash_texto_nlp=h,x=float(x),y=float(y),cluster=code) for (h,_),(x,y),code in zip(train,projection,labels)))
    folder.mkdir(parents=True,exist_ok=True); joblib.dump(artifact,folder/model_file,compress=3)
    sha=digest(folder/model_file); version=method.lower()+'-'+sha[:12]
    codes=list(range(len(words))) if method=='LDA' else artifact['codes']
    catalog=[dict(codigo_topico=f'{version}-T{i:03d}',idioma='es',etiqueta=' / '.join(terms[:3]),
        descripcion='Título provisional; revisar ejemplos antes de nombrar dimensiones de negocio.',
        palabras_clave='; '.join(terms),version_modelo=version,metodo=method,
        validacion_etiqueta='PROPUESTA_AUTOMATICA') for i,terms in zip(codes,words)]
    info=dict(sha256=sha,version=version,method=method,catalog=catalog,training_texts=len(train),
              training_hash=corpus_hash,trials=trials,pilot=pilot,holdout_hashes=[h for h,_ in held],
              embedding_model=MODEL_NAME if method!='LDA' else None,embedding_revision=MODEL_REVISION if method!='LDA' else None)
    info['environment']={name:importlib.metadata.version(name) for name in ('numpy','scikit-learn','joblib','bertopic','sentence-transformers','transformers','torch','umap-learn','hdbscan')}
    info['python']=sys.version
    if method=='S-BERT': info['clustering_schema']=CLUSTERING_SCHEMA
    meta_set(cx,model_key(method),info); cx.commit(); atomic_json(folder/('model_manifest_v2.json' if method=='S-BERT' else 'model_manifest.json'),info)
    return artifact,info,encoder if method!='LDA' else None

def predict(artifact,info,items,cx,progress,stop,encoder=None):
    import numpy as np
    if artifact['method']=='LDA':
        matrix=artifact['vectorizer'].transform([t for _,t in items]); weights=artifact['model'].transform(matrix)
        result=[]
        for i,w in enumerate(weights):
            if matrix[i].nnz==0: result.append(('SIN_SENAL_TEMATICA',[])); continue
            w=w/w.sum(); pairs=[(f"{info['version']}-T{j:03d}",float(v)) for j,v in enumerate(w) if v>0]
            result.append(('OK',pairs))
        return result,encoder
    if encoder is None: encoder=Embeddings(cx,progress,stop)
    vectors=encoder.get(items); labels,confidence=artifact['model'].transform([t for _,t in items],vectors)
    # HDBSCAN fuerza un tópico dominante por documento, no una mezcla LDA. Peso 1 es indicador de pertenencia.
    result=[('FUERA_DE_GRUPO',[]) if label<0 else ('OK',[(f"{info['version']}-T{label:03d}",1.)]) for label in labels]
    return result,encoder

def infer(method,artifact,info,cx,source,progress,stop,pilot,encoder):
    table=assignment_table(method)
    held=set(info['holdout_hashes']); train,_held,_hash=samples(source,progress,pilot)
    allowed=held|{h for h,_ in train} if pilot else None
    total=len(allowed) if pilot else source.execute('SELECT COUNT(*) FROM texts').fetchone()[0]
    done=cx.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]; batch=[]
    def commit(batch,encoder):
        eligible=[(h,t) for h,t,lang in batch if eligibility(t,lang) is None]
        predicted,encoder=predict(artifact,info,eligible,cx,progress,stop,encoder) if eligible else ([],encoder)
        lookup={h:r for (h,_),r in zip(eligible,predicted)}
        for h,t,lang in batch:
            status,pairs=lookup.get(h,(eligibility(t,lang),[]))
            if status=='OK' and lang=='xx': status='OK_IDIOMA_INCIERTO'
            cx.execute(f'INSERT INTO {table} VALUES (?,?,?)',(h,status,json.dumps(pairs)))
        cx.commit(); return encoder
    for r in source.execute('SELECT text_hash,text,language FROM texts ORDER BY text_hash'):
        h=r['text_hash']
        if allowed is not None and h not in allowed: continue
        if cx.execute(f'SELECT 1 FROM {table} WHERE hash=?',(h,)).fetchone(): continue
        batch.append((h,r['text'],r['language']))
        if len(batch)>=256:
            if stop(): raise InterruptedError('Parada segura de inferencia')
            encoder=commit(batch,encoder); done+=len(batch); batch=[]
            progress.update('inferir_'+method,done,total,'Tópicos confirmados sin repetir sentimiento',ultimo_checkpoint=utcnow(),unidad='textos')
    if batch: encoder=commit(batch,encoder); done+=len(batch)
    meta_set(cx,'inference_done',True); cx.commit()
    return done

def review_sample(cx,source,folder,info):
    import heapq
    examples=defaultdict(list)
    for r in source.execute('SELECT text_hash,text FROM texts ORDER BY text_hash'):
        a=cx.execute(f'SELECT weights FROM {assignment_table(info["method"])} WHERE hash=?',(r['text_hash'],)).fetchone()
        if not a: continue
        pairs=json.loads(a[0])
        if not pairs: continue
        code,weight=max(pairs,key=lambda x:x[1]); h=r['text_hash']; heap=examples[code]
        value=(-int(h,16),h,r['text'],weight)
        if len(heap)<20: heapq.heappush(heap,value)
        elif value[0]>heap[0][0]: heapq.heapreplace(heap,value)
    save_csv(folder,'muestra_revision_topicos.csv',['codigo_topico','hash_texto_nlp','texto','peso_dominante'],
         (dict(codigo_topico=code,hash_texto_nlp=h,texto=t,peso_dominante=w) for code,heap in sorted(examples.items()) for _,h,t,w in sorted(heap)))

def export(cx,folder,info,progress,pilot,source_report):
    lookup={r['hash']:(r['status'],json.loads(r['weights'])) for r in cx.execute(f'SELECT * FROM {assignment_table(info["method"])}')}
    outputs=[]; seen=set(); thematic=0; status_counts=Counter()
    with (FINAL/'base_madre_resenas.csv').open(encoding='utf-8-sig',newline='') as f: fields=next(csv.reader(f))
    def rows():
        nonlocal thematic
        for n,(_,r) in enumerate(read_csv(FINAL/'base_madre_resenas.csv'),1):
            h=r['hash_texto_nlp']
            if pilot and h not in lookup: continue
            if h not in lookup: raise ValueError('Falta una asignación; no se declara éxito')
            state,pairs=lookup[h]; r['estado_topicos']=state
            r['topico_dominante']=max(pairs,key=lambda x:x[1])[0] if pairs else ''
            r['version_modelo_topicos']=info['version']; status_counts[state]+=1; thematic+=bool(pairs)
            seen.add(r['id_review']); yield r
            if n%50000==0: progress.update('exportar_'+info['method'],n,source_report['counts']['reviews'],'Todas las columnas originales y NLP común conservados')
    outputs.append(save_csv(folder,'base_madre_resenas.csv',fields,rows()))
    expected=source_report['counts']['reviews']
    if not pilot and len(seen)!=expected: raise ValueError('Se perdieron o multiplicaron reseñas')
    outputs.append(save_csv(folder,'catalogo_dimensiones_latentes.csv',list(info['catalog'][0]),info['catalog']))
    def bridges():
        for _,r in read_csv(folder/'base_madre_resenas.csv'):
            pairs=lookup[r['hash_texto_nlp']][1]
            if not pairs: continue
            if abs(sum(w for _,w in pairs)-1)>1e-6: raise ValueError('Pesos no reconciliados')
            dominant=max(pairs,key=lambda x:x[1])[0]
            for code,w in pairs:
                yield dict(id_review=r['id_review'],codigo_topico=code,peso=format(w,'.9f'),es_dominante=int(code==dominant),version_modelo=info['version'])
    outputs.append(save_csv(folder,'resena_dimension_latente.csv',['id_review','codigo_topico','peso','es_dominante','version_modelo'],bridges()))
    if pilot:
        place_counts=Counter((r['codigo_pais'],r['google_place_id']) for _,r in read_csv(folder/'base_madre_resenas.csv'))
        def place_rows():
            for _,r in read_csv(FINAL/'base_madre_lugares.csv'):
                r['n_resenas_extraidas']=place_counts[(r['codigo_pais'],r['id'])]; yield r
        with (FINAL/'base_madre_lugares.csv').open(encoding='utf-8-sig',newline='') as f: place_fields=next(csv.reader(f))
        outputs.append(save_csv(folder,'base_madre_lugares.csv',place_fields,place_rows()))
    else:
        shutil.copy2(FINAL/'base_madre_lugares.csv',folder/'base_madre_lugares.csv')
        po=next(o for o in source_report['outputs'] if o['file']=='base_madre_lugares.csv'); outputs.append(po)
    report={**source_report,'counts':{**source_report['counts'],'reviews':len(seen)},'outputs':outputs,
       'method':info['method'],'modelo_topicos':info,'estado':'EXPORTADO','estados_topicos':dict(status_counts),
       'resenas_con_topicos':thematic,'pilot':pilot,'validacion_independiente':None,
       'limitations':source_report['limitations']+['S-BERT: peso 1 indica pertenencia al grupo, no probabilidad de tópico.' if info['method']=='S-BERT' else 'LDA: pesos posteriores; no equivalen a pesos NMF.',
            'Comparación principal sobre corpus español común; cobertura de idioma incierto es análisis ampliado.']}
    atomic_json(folder/'validacion_final.json',report)
    validate(folder)
    return len(seen)

def run(method,pilot=False):
    source_report=baseline(); WORK.mkdir(parents=True,exist_ok=True)
    mode='piloto' if pilot else 'completo'; working=WORK/mode/method; working.mkdir(parents=True,exist_ok=True)
    folder=working/'salidas' if pilot else FINAL/method
    stop_file=WORK/'stop.request'; start_stamp=stop_file.stat().st_mtime_ns if stop_file.exists() else 0
    stopped=[False]
    signal.signal(signal.SIGINT,lambda *_:stopped.__setitem__(0,True))
    stop=lambda:stopped[0] or (stop_file.exists() and stop_file.stat().st_mtime_ns>start_stamp)
    lock=ProcessLock(WORK/'process.lock'); progress=Progress('topicos_comparacion')
    source=ro_source(); cx=connection(working/'checkpoint.sqlite')
    try:
        spec=dict(version=VERSION,method=method,pilot=pilot,source_csv_sha256=digest(FINAL/'base_madre_resenas.csv'),
                  model=MODEL_NAME,revision=MODEL_REVISION)
        old=meta_get(cx,'spec')
        if old and old!=spec: raise ValueError('Cambió configuración/fuente; no mezclar checkpoints')
        meta_set(cx,'spec',spec); cx.commit()
        if not pilot:
            gate=WORK/'piloto'/method/'salidas/validacion_final.json'
            gate_report=json.loads(gate.read_text(encoding='utf8')) if gate.exists() else {}
            if gate_report.get('estado')!='EXPORTADO' or gate_report.get('validacion_independiente',{}).get('estado')!='VALIDADO':
                raise ValueError('Primero debe completar el piloto de esta técnica')
            if gate_report.get('sources')!=source_report.get('sources'):
                raise ValueError('El piloto pertenece a otras fuentes; no sirve como validación')
            if method=='S-BERT' and gate_report.get('modelo_topicos',{}).get('clustering_schema')!=CLUSTERING_SCHEMA:
                raise ValueError('Primero debe pasar el piloto de agrupación diferenciada v2')
        progress.update('inicio_'+method,0,0,'Experimento independiente; sentimiento y datos originales no cambian')
        artifact,info,encoder=fit(method,cx,source,working,progress,stop,pilot)
        infer(method,artifact,info,cx,source,progress,stop,pilot,encoder)
        review_sample(cx,source,folder,info)
        exported=export(cx,folder,info,progress,pilot,source_report)
        progress.update('completado_'+method,exported,exported,
             'Salidas validadas; títulos requieren revisión semántica',estado='COMPLETADO')
    except InterruptedError:
        cx.rollback(); progress.update(message='Parada segura; checkpoint conservado',estado='DETENIDO')
        raise SystemExit(130)
    except Exception as exc:
        cx.rollback(); progress.update(message=str(exc),estado='ERROR',errores=1); raise
    finally: cx.close(); source.close(); progress.close(); lock.close()

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('method',choices=['NMF','LDA','S-BERT','DETENER']); ap.add_argument('--pilot',action='store_true')
    args=ap.parse_args()
    if args.method=='DETENER': atomic_json(WORK/'stop.request',{'solicitud':utcnow()})
    elif args.method=='NMF': baseline()
    else: run(args.method,args.pilot)
