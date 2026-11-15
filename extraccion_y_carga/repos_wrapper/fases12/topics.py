"""Tópicos por idioma: TF-IDF/NMF y alternativa LDA, con pesos normalizados."""
import hashlib
import json
import math
import random
import warnings
from collections import defaultdict

from common import meta_get,meta_set,atomic_json,digest

STOPWORDS={
 'es':'''a al algo algunas algunos ante antes como con contra cual cuando de del desde donde durante e el ella ellas ellos en entre era es esa esas ese esos esta estas este estos esto fue ha hasta hay la las le les lo los mas me mi mis mucho muy nada ni no nos nuestra nuestro o para pero poco por porque que quien se sin sobre son su sus te tiene todos tu un una uno unos unas y ya yo hemos hay estar lugar museo museos visitar visita visitas mexico peru'''.split(),
 'pt':'''a as ao aos o os um uma uns umas de da das do dos em no na nos nas e ou que com por para pelo pela muito mais mas nao se sua seu suas seus foi sao ser uma este esta eu voce lugar museu museus visitar visita'''.split(),
 'fr':'''a au aux avec ce ces cette dans de des du elle en et il ils la le les leur lui mais ne nous on ou par pas pour que qui sa se ses son sur un une vous est sont tres plus musee musees visite visiter'''.split(),
 'it':'''a al alla alle con da dal dalla di del della delle e ed gli i il in la le lo ma molto non o per piu che si sono su un una uno museo musei visita visitare'''.split(),
 'de':'''aber als am an auch auf aus bei das dem den der des die ein eine einen einer es fur im in ist mit nicht oder sehr sie sind und von war wie zu zum museum museen'''.split(),
 'nl':'''aan als bij de deze die dit een en er het ik in is met niet of om op ook te van voor was zijn museum musea'''.split(),
}


def quality(matrix,components):
    import numpy as np
    indices=[row.argsort()[-10:][::-1] for row in components]
    n=matrix.shape[0]; values=[]
    for topic in indices:
        binary=(matrix[:,topic]>0).toarray().astype(np.int32)
        df=binary.sum(axis=0); pair=binary.T@binary
        for i in range(len(topic)):
            for j in range(i+1,len(topic)):
                if not pair[i,j]: values.append(-1.); continue
                pij=(pair[i,j]+.5)/(n+1); pi=(df[i]+.5)/(n+1); pj=(df[j]+.5)/(n+1)
                values.append(math.log(pij/(pi*pj))/-math.log(pij))
    diversity=len({int(i) for topic in indices for i in topic})/max(1,sum(len(t) for t in indices))
    coherence=float(np.mean(values)) if values else -1.
    return dict(npmi=coherence,diversity=diversity,selection_score=coherence+.15*diversity)


def fit_and_assign(cx,folder,progress,stop_requested,threads=6):
    import joblib
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer,CountVectorizer,ENGLISH_STOP_WORDS
    from sklearn.decomposition import NMF,LatentDirichletAllocation
    from threadpoolctl import threadpool_limits
    existing=meta_get(cx,'topic_manifest')
    if existing:
        manifest=existing
        for item in manifest['models']:
            if digest(folder/item['file'])!=item['sha256']: raise ValueError('Artefacto de tópicos modificado')
    else:
        folder.mkdir(parents=True,exist_ok=True)
        models=[]; catalog=[]; score_reports=[]
        language_counts=dict(cx.execute("SELECT language,COUNT(*) FROM texts WHERE text<>'' GROUP BY language").fetchall())
        allowed=set(STOPWORDS)|{'en'}
        for language in sorted(allowed):
            # Reseñas muy breves se pueden clasificar por sentimiento, no dan suficiente señal temática.
            candidates=defaultdict(list)
            query='''SELECT t.text_hash,t.text,MIN(r.country) country FROM texts t JOIN reviews r USING(text_hash)
                     WHERE t.language=? GROUP BY t.text_hash ORDER BY t.text_hash'''
            for row in cx.execute(query,(language,)):
                if len(row['text'].split())>=4: candidates[row['country']].append((row['text_hash'],row['text']))
            if sum(len(v) for v in candidates.values())<200: continue
            rng=random.Random(20261011)
            selected=[]
            for country,items in sorted(candidates.items()):
                rng.shuffle(items); selected.extend(items[:10000])
            selected.sort()
            texts=[text for _,text in selected]
            stops=list(ENGLISH_STOP_WORDS) if language=='en' else STOPWORDS[language]
            vectorizer=TfidfVectorizer(strip_accents='unicode',lowercase=True,stop_words=stops,
                 ngram_range=(1,2),max_features=16000,min_df=3,max_df=.85,sublinear_tf=True,dtype=np.float32)
            progress.update('entrenar_topicos',0,len(texts),f'{language}; vocabulario y modelos candidatos')
            try:
                matrix=vectorizer.fit_transform(texts)
            except ValueError as exc:
                score_reports.append(dict(language=language,skipped=str(exc)))
                continue
            if matrix.shape[1]<20: continue
            best=None; trials=[]
            with threadpool_limits(limits=threads):
                for k in ([4,6] if len(texts)<2000 else [6,8,10]):
                    if k>=min(matrix.shape): continue
                    try:
                        model=NMF(n_components=k,init='nndsvda',random_state=20261011,max_iter=250,tol=.001)
                        with warnings.catch_warnings(record=True) as caught:
                            model.fit(matrix)
                        metrics=quality(matrix,model.components_)
                        trial=dict(method='TFIDF_NMF',k=k,iterations=int(model.n_iter_),warnings=[str(x.message) for x in caught],**metrics)
                        trials.append(trial)
                        if best is None or metrics['selection_score']>best[0]: best=(metrics['selection_score'],model,vectorizer,'TFIDF_NMF',k)
                    except (ValueError,MemoryError) as exc:
                        trials.append(dict(method='TFIDF_NMF',k=k,error=str(exc)))
                    progress.update('entrenar_topicos',k,10,f'{language}; NMF candidato evaluado')
                    if stop_requested(): return False
                if best is None:
                    vectorizer=CountVectorizer(strip_accents='unicode',stop_words=stops,max_features=16000,min_df=3,max_df=.85)
                    matrix=vectorizer.fit_transform(texts)
                    model=LatentDirichletAllocation(n_components=6,learning_method='online',max_iter=8,
                                                   random_state=20261011,n_jobs=1)
                    model.fit(matrix); metrics=quality(matrix,model.components_)
                    best=(metrics['selection_score'],model,vectorizer,'COUNT_LDA',6)
                    trials.append(dict(method='COUNT_LDA',k=6,**metrics))
            _,model,vectorizer,method,k=best
            file=f'topicos_{language}.joblib'
            joblib.dump(dict(model=model,vectorizer=vectorizer),folder/file,compress=3)
            artifact_sha=digest(folder/file)
            version=language+'-'+method.lower()+'-'+artifact_sha[:12]
            features=vectorizer.get_feature_names_out()
            for i,component in enumerate(model.components_):
                words=[str(features[j]) for j in component.argsort()[-12:][::-1]]
                code=f'{version}-T{i+1:02d}'
                catalog.append(dict(codigo_topico=code,idioma=language,etiqueta=' / '.join(words[:3]),
                    descripcion='Tópico descubierto por coocurrencia; etiqueta descriptiva pendiente de revisión del equipo.',
                    palabras_clave='; '.join(words),version_modelo=version,metodo=method,
                    validacion_etiqueta='PROPUESTA_AUTOMATICA'))
            models.append(dict(language=language,file=file,sha256=artifact_sha,version=version,k=k,
                               method=method,training_texts=len(texts),source_hashes_sha256=hashlib.sha256('\n'.join(h for h,_ in selected).encode()).hexdigest()))
            score_reports.append(dict(language=language,candidates=trials,selected_k=k,selected_method=method))
        if not models: raise ValueError('Ningún idioma tiene suficiente señal para descubrir tópicos; no se simulan resultados')
        manifest=dict(models=models,evaluations=score_reports,
                      weights='Pesos NMF normalizados por reseña; no probabilidades calibradas.',
                      training='Máximo 10 mil textos únicos por país y por idioma; semilla fija.',
                      language_counts=language_counts)
        meta_set(cx,'topic_manifest',manifest)
        meta_set(cx,'topic_catalog',catalog)
        meta_set(cx,'topic_version',hashlib.sha256(json.dumps(models,sort_keys=True).encode()).hexdigest()[:16])
        cx.commit()
        atomic_json(folder/'manifest.json',manifest)
    total=cx.execute('SELECT COUNT(*) FROM texts').fetchone()[0]
    for item in manifest['models']:
        language=item['language']; artifact=joblib.load(folder/item['file'])
        vectorizer=artifact['vectorizer']; model=artifact['model']
        while True:
            rows=cx.execute('SELECT text_hash,text FROM texts WHERE language=? AND topic_status IS NULL LIMIT 512',(language,)).fetchall()
            if not rows: break
            with threadpool_limits(limits=threads):
                matrix=vectorizer.transform([r['text'] for r in rows])
                weights=model.transform(matrix)
            for row,w in zip(rows,weights):
                # Documentos fuera del vocabulario o de menos de cuatro palabras no se fuerzan a un tópico.
                if not np.isfinite(w).all(): raise ValueError('Pesos temáticos no finitos; no se oculta el fallo como falta de señal')
                if len(row['text'].split())<4 or float(w.sum())<=1e-12:
                    status='SIN_SENAL_TEMATICA'; assignments=[]
                else:
                    w=w/w.sum()
                    assignments=[(f"{item['version']}-T{i+1:02d}",float(value)) for i,value in enumerate(w) if value>0]
                    status='OK'
                cx.execute('UPDATE texts SET topic_status=?,topics_json=? WHERE text_hash=?',
                           (status,json.dumps(assignments),row['text_hash']))
            cx.commit()
            done=cx.execute('SELECT COUNT(*) FROM texts WHERE topic_status IS NOT NULL').fetchone()[0]
            progress.update('asignar_topicos',done,total,language+'; lote confirmado')
            if stop_requested(): return False
    cx.execute("UPDATE texts SET topic_status=CASE WHEN text='' THEN 'SIN_TEXTO' ELSE 'IDIOMA_SIN_MODELO_TEMATICO' END,topics_json='[]' WHERE topic_status IS NULL")
    meta_set(cx,'phase2_topics_done',True); cx.commit()
    return True
