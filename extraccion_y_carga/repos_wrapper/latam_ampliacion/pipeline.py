"""Ampliación PE+MX+AR: fuentes inmutables, checkpoint nuevo y modelos fijos.

No ejecuta scraping, entrenamiento, publicación Git ni aprobación humana.
Los CSV son tablas de intercambio del pipeline, no libros Excel.
"""
import argparse
import csv
import gzip
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
from collections import Counter

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/'repos_wrapper/fases12'))
from common import (connect as common_connect, meta_get, meta_set, atomic_json, normalized_text, text_key,
                    REVIEW_FIELDS, digest, iso_date, integer, utcnow, ProcessLock, segments)
from dataset import DERIVED
sys.path.insert(0, str(Path(__file__).resolve().parent))
from resilience import RetryingConnection

VERSION = 'latam-ampliacion-2026-10-22-v1'
WORK = REPO/'data/preparacion_latam/ampliacion_2026-10-22_v1'
OLD = REPO/'data/preparacion_latam/completo'
TOPIC = OLD/'comparacion_topicos/completo/S-BERT'
COUNTRIES = {'PE': ('Perú', 'PER'), 'MX': ('México', 'MEX'), 'AR': ('Argentina', 'ARG')}
EXTRA = ['corrida', 'registro_completo', 'pais']
STOP = WORK/'stop.request'
SOURCE_FILES = [
    ('PE_AR', 'reviews', 'data/resenas/paquetes/comentarios_museos_consolidado.csv.gz'),
    ('MX', 'reviews', 'data/resenas/resenas_museos_consolidadas_mexico.csv'),
    *[(c, 'places', f'data/lugares/base_museos_{n}.csv') for c,n in [('PE','peru'),('MX','mexico'),('AR','argentina')]],
    ('AR', 'verification', 'data/resenas/paquetes/comentarios_museos_crudo_argentina.csv.gz'),
]


def connect(path):
    cx = common_connect(path, factory=RetryingConnection, timeout=5)
    def report_wait(state, attempts):
        value = dict(state=state, attempts=attempts, pid=os.getpid(), updated=utcnow(),
                     message='COMMIT en espera; se conserva la transacción sin repetir el lote')
        print(json.dumps(value, ensure_ascii=False), flush=True)
        try:
            atomic_json(WORK/'bloqueo_sqlite.json', value)
        except OSError as exc:
            print('Aviso: no se pudo escribir telemetría: '+str(exc), flush=True)
    cx.on_commit_wait = report_wait
    return cx


class Progress:
    def update(self, phase=None, done=None, total=None, message='', **extra):
        value = dict(version=VERSION, pid=os.getpid(), phase=phase, done=done,
                     total=total, message=message, updated=utcnow(), **extra)
        atomic_json(WORK/'progreso.json', value)
        # Estos eventos se emiten después del COMMIT, nunca durante inferencia.
        if extra.get('ultimo_checkpoint') or phase == 'topicos_41':
            atomic_json(WORK/'checkpoint_confirmado.json', value)
        print(json.dumps(value, ensure_ascii=False), flush=True)


def stopped():
    return STOP.exists()


def ro(path):
    cx = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    cx.row_factory = sqlite3.Row
    return cx


def rows(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        for number, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f'CSV mal formado: {path.name}, registro {number}')
            yield number, row


def museum(category):
    return category.strip().casefold() == 'museo' or category.strip().casefold().startswith('museo ')


def row_quality(row, known_places, country):
    flags = []
    if country+':'+row['google_place_id'] not in known_places: flags.append('LUGAR_SIN_BASE')
    if not museum(row['categoria_google']): flags.append('CATEGORIA_FUERA_CRITERIO')
    if not row['rating']: flags.append('RATING_AUSENTE')
    else:
        try:
            if float(row['rating']) not in (1,2,3,4,5): flags.append('RATING_INVALIDO')
        except ValueError: flags.append('RATING_INVALIDO')
    dates = {}
    for field in ('review_date','retrieval_date'):
        if not row[field]: flags.append(field.upper()+'_AUSENTE')
        else:
            try: dates[field] = iso_date(row[field])
            except (ValueError, OverflowError): flags.append(field.upper()+'_INVALIDA')
    if len(dates)==2 and dates['review_date']>dates['retrieval_date']:
        flags.append('FECHA_RESENA_POSTERIOR_EXTRACCION')
    try: integer(row['n_review_user'])
    except (ValueError, OverflowError): flags.append('HISTORIAL_AUTOR_INVALIDO')
    if '\ufffd' in ''.join(row.values()): flags.append('CARACTER_REEMPLAZO_UNICODE')
    if not row['relative_date']: flags.append('FECHA_RELATIVA_AUSENTE')
    if not row['nombre_lugar'].strip(): flags.append('NOMBRE_LUGAR_AUSENTE')
    return flags


def content_hash(row):
    return hashlib.sha256(json.dumps({k:row[k] for k in REVIEW_FIELDS},
        ensure_ascii=False, sort_keys=True, separators=(',',':')).encode()).hexdigest()


def manifest():
    result = []
    for country, kind, rel in SOURCE_FILES:
        path = REPO/rel
        with (gzip.open(path,'rt',encoding='utf-8-sig',newline='') if path.suffix=='.gz'
              else path.open(encoding='utf-8-sig',newline='')) as stream:
            columns = next(csv.reader(stream))
        if kind in ('reviews','verification') and not set(REVIEW_FIELDS)<=set(columns):
            raise ValueError('Faltan columnas fuente: '+rel)
        result.append(dict(country=country,kind=kind,path=rel,columns=columns,
                           bytes=path.stat().st_size,sha256=digest(path)))
    return result


def prepare(cx, progress):
    sources = manifest()
    spec = dict(version=VERSION, sources=sources, normalization='common.normalized_text:NFC_whitespace_v1',
                categories='Museo y subcategorías Museo; conservar original',
                missing='conservar y marcar; no inventar rating ni fecha')
    if meta_get(cx,'input_spec') not in (None,spec):
        raise ValueError('Fuentes cambiaron: crear otra versión, no mezclar checkpoints')
    meta_set(cx,'input_spec',spec); cx.commit()
    atomic_json(WORK/'manifiesto_fuentes.json',spec)
    if meta_get(cx,'prepared'): return
    for source in (s for s in sources if s['kind']=='places'):
        country = source['country']
        if meta_get(cx,'places_done:'+country): continue
        bounds = {'AR':(-56,-21,-74,-53),'PE':(-19,1,-82,-68),'MX':(14,33,-119,-86)}[country]
        for line,row in rows(REPO/source['path']):
            if not row['id'].strip(): raise ValueError('ID de lugar vacío')
            flags=[]
            if not museum(row['category']): flags.append('CATEGORIA_FUERA_CRITERIO')
            try:
                lat,lon=float(row['lat']),float(row['lon'])
                if not math.isfinite(lat+lon) or not (-90<=lat<=90 and -180<=lon<=180): flags.append('COORDENADAS_INVALIDAS')
                elif not (bounds[0]<=lat<=bounds[1] and bounds[2]<=lon<=bounds[3]): flags.append('FUERA_CAJA_GEOGRAFICA_APROXIMADA')
            except ValueError: flags.append('COORDENADAS_INVALIDAS')
            key=country+':'+row['id']
            cx.execute('INSERT INTO places VALUES (?,?,?,?,?,?)',
                (key,country,row['id'],json.dumps(row,ensure_ascii=False),source['path'],line))
            cx.execute('INSERT INTO place_quality VALUES (?,?)',(key,json.dumps(flags)))
        meta_set(cx,'places_done:'+country,True); cx.commit()
    known={r[0] for r in cx.execute('SELECT place_key FROM places')}
    for source in (s for s in sources if s['kind']=='reviews'):
        tag=source['country']; cursor=meta_get(cx,'cursor:'+tag,1)
        if meta_get(cx,'reviews_done:'+tag): continue
        for line,row in rows(REPO/source['path']):
            if line<=cursor: continue
            country = 'MX' if tag=='MX' else {'Perú':'PE','Peru':'PE','PE':'PE','Argentina':'AR','AR':'AR'}.get(row.get('pais'))
            if country not in COUNTRIES: raise ValueError('País no reconocido')
            if not row['id_review'].strip() or not row['google_place_id'].strip():
                raise ValueError('ID de reseña/lugar vacío: no se puede crear clave estable')
            flags=row_quality(row,known,country)
            payload=json.dumps(row,ensure_ascii=False,separators=(',',':'))
            previous=cx.execute('SELECT country,raw_json FROM reviews WHERE review_id=?',(row['id_review'],)).fetchone()
            if previous:
                if previous['country']!=country or previous['raw_json']!=payload:
                    raise ValueError('Colisión nueva de ID: requiere reconciliación explícita')
                cx.execute('INSERT INTO duplicate_sources VALUES (?,?,?)',(row['id_review'],source['path'],line))
            else:
                cx.execute('INSERT INTO reviews VALUES (?,?,?,?,?,?,?)',
                    (row['id_review'],country,country+':'+row['google_place_id'],payload,text_key(row['caption']),source['path'],line))
                cx.execute('INSERT INTO review_quality VALUES (?,?,?)',(row['id_review'],json.dumps(flags),content_hash(row)))
            if (line-1)%10000==0:
                meta_set(cx,'cursor:'+tag,line); cx.commit()
                progress.update('unificar',line-1,None,tag)
                if stopped(): return
        meta_set(cx,'reviews_done:'+tag,True); cx.commit()
    if not meta_get(cx,'texts_indexed'):
        batch=[]
        for item in cx.execute('SELECT text_hash,raw_json FROM reviews'):
            batch.append((item['text_hash'],normalized_text(json.loads(item['raw_json'])['caption'])))
            if len(batch)>=10000:
                cx.executemany('INSERT OR IGNORE INTO texts(text_hash,text) VALUES (?,?)',batch)
                cx.commit(); batch=[]
        cx.executemany('INSERT OR IGNORE INTO texts(text_hash,text) VALUES (?,?)',batch)
        meta_set(cx,'texts_indexed',True); cx.commit()
    if not meta_get(cx,'argentina_raw_checked'):
        source=next(s for s in sources if s['kind']=='verification')
        for line,row in rows(REPO/source['path']):
            cx.execute('INSERT OR REPLACE INTO argentina_raw_check VALUES (?,?)',(row['id_review'],content_hash(row)))
            if line%10000==0: cx.commit()
        cx.commit()
        missing=cx.execute("SELECT count(*) FROM argentina_raw_check a LEFT JOIN reviews r ON a.review_id=r.review_id WHERE r.country IS NULL OR r.country<>'AR'").fetchone()[0]
        absent=cx.execute("SELECT count(*) FROM reviews r LEFT JOIN argentina_raw_check a USING(review_id) WHERE r.country='AR' AND a.review_id IS NULL").fetchone()[0]
        changed=cx.execute("SELECT count(*) FROM argentina_raw_check a JOIN review_quality q USING(review_id) WHERE a.content_hash<>q.content_hash").fetchone()[0]
        meta_set(cx,'argentina_raw_check',dict(raw_ids=cx.execute('select count(*) from argentina_raw_check').fetchone()[0],missing_in_published=missing,published_not_in_raw=absent,changed_original_fields=changed))
        if missing or absent: raise ValueError('Argentina cruda/publicada no concilia IDs')
        meta_set(cx,'argentina_raw_checked',True); cx.commit()
    meta_set(cx,'prepared',True); cx.commit()
    audit(cx)
    progress.update('unificacion_completa',cx.execute('select count(*) from reviews').fetchone()[0],None,'Sin sobrescribir las fuentes')


def audit(cx):
    report=dict(version=VERSION,updated=utcnow(),argentina_raw_check=meta_get(cx,'argentina_raw_check'),countries={})
    for country in COUNTRIES:
        flags=Counter(); categories=Counter(); without_text=0
        for row in cx.execute('SELECT r.raw_json,q.flags FROM reviews r JOIN review_quality q USING(review_id) WHERE r.country=?',(country,)):
            raw=json.loads(row['raw_json']); flags.update(json.loads(row['flags']))
            categories[raw['categoria_google']]+=1; without_text+=not bool(raw['caption'].strip())
        n=cx.execute('SELECT count(*) FROM reviews WHERE country=?',(country,)).fetchone()[0]
        places=cx.execute('SELECT count(DISTINCT place_key) FROM reviews WHERE country=?',(country,)).fetchone()[0]
        pflags=Counter()
        for row in cx.execute('SELECT q.flags FROM place_quality q JOIN places p USING(place_key) WHERE p.country=?',(country,)):
            pflags.update(json.loads(row['flags']))
        report['countries'][country]=dict(reviews=n,places_with_reviews=places,with_text=n-without_text,without_text=without_text,
            quality_flags=dict(flags),categories=dict(categories),place_quality_flags=dict(pflags),
            place_universe=cx.execute('SELECT count(*) FROM places WHERE country=?',(country,)).fetchone()[0])
    report['reviews']=sum(r['reviews'] for r in report['countries'].values())
    report['unique_texts_nonempty']=cx.execute("SELECT count(*) FROM texts WHERE text<>''").fetchone()[0]
    report['duplicate_sources']=cx.execute('SELECT count(*) FROM duplicate_sources').fetchone()[0]
    report['foreign_key_errors']=len(cx.execute('PRAGMA foreign_key_check').fetchall())
    report['limitations']=['Integridad de archivos/relaciones no prueba exactitud respecto a Google ni exhaustividad del scraping.',
        'Subcategorías de museo incluidas en PE/AR; MX recolectado como Museo. Usar estrato comparable al comparar países.',
        'review_date fuente no se interpreta automáticamente como fecha exacta observada de publicación.',
        'La interfaz en español no demuestra el idioma original. El detector describe el texto almacenado, que puede contener traducción.']
    atomic_json(WORK/'auditoria_datos.json',report)
    return report


NLP_COLUMNS=['language','language_score','language_engine','sentiment','sentiment_score','confidence','p_negative','p_neutral','p_positive','sentiment_model','tokens','chunks','nlp_status']


def reconcile_previous(cx):
    if meta_get(cx,'reconciliation_previous'): return
    old=ro(OLD/'checkpoint.sqlite')
    reconciliation={c:dict(previous=0,missing=0,changed_fields={}) for c in COUNTRIES}
    for item in old.execute('SELECT review_id,country,raw_json FROM reviews'):
        stats=reconciliation[item['country']]; stats['previous']+=1
        current=cx.execute('SELECT raw_json FROM reviews WHERE review_id=?',(item['review_id'],)).fetchone()
        if not current: stats['missing']+=1; continue
        before=json.loads(item['raw_json']); after=json.loads(current['raw_json'])
        for key in REVIEW_FIELDS:
            if before.get(key)!=after.get(key):
                stats['changed_fields'][key]=stats['changed_fields'].get(key,0)+1
    for country,stats in reconciliation.items():
        stats['current']=cx.execute('SELECT count(*) FROM reviews WHERE country=?',(country,)).fetchone()[0]
        stats['new_ids']=stats['current']-(stats['previous']-stats['missing'])
    old.close()
    atomic_json(WORK/'conciliacion_version_anterior.json',reconciliation)
    if any(stats['missing'] for stats in reconciliation.values()):
        raise ValueError('Hay IDs anteriores ausentes; revisar antes de ampliar el NLP')
    meta_set(cx,'reconciliation_previous',reconciliation); cx.commit()


def reuse(cx,progress):
    if meta_get(cx,'cache_reused'): return
    old=ro(OLD/'checkpoint.sqlite'); config=meta_get(old,'nlp_configuration')
    if config['selected']!='xlm_t' or config['max_tokens']!=256 or config['min_confidence']!=.55:
        raise ValueError('Configuración original NLP inesperada')
    meta_set(cx,'nlp_configuration',config)
    meta_set(cx,'packages_original',meta_get(old,'packages'))
    meta_set(cx,'sentiment_models_original',meta_get(old,'sentiment_models'))
    meta_set(cx,'cache_text_normalization','NFC_whitespace_v1 (common.py compartido; igualdad de texto verificada)')
    count=0
    for item in old.execute('SELECT text_hash,text,'+','.join(NLP_COLUMNS)+' FROM texts WHERE nlp_status IS NOT NULL'):
        current=cx.execute('SELECT text FROM texts WHERE text_hash=?',(item['text_hash'],)).fetchone()
        if current:
            if current['text']!=item['text']: raise ValueError('Colisión de hash de texto')
            cx.execute('UPDATE texts SET '+','.join(c+'=?' for c in NLP_COLUMNS)+' WHERE text_hash=?',
                       tuple(item[c] for c in NLP_COLUMNS)+(item['text_hash'],))
            count+=1
            if count%5000==0: cx.commit()
    old.close()
    reconcile_previous(cx)
    original=ro(TOPIC/'checkpoint.sqlite'); info=meta_get(original,'model_v2')
    disk=json.loads((TOPIC/'model_manifest_v2.json').read_text(encoding='utf-8'))
    if info!=disk or len(info['catalog'])!=41: raise ValueError('Modelo original de 41 tópicos no coincide')
    meta_set(cx,'topic_model',info); meta_set(cx,'topic_model_file_sha256',digest(TOPIC/'model_v2.joblib'))
    assignments=0; vectors=0
    for item in original.execute('SELECT a.hash,a.status,a.weights FROM assignments_v2 a'):
        current=cx.execute('SELECT language,text FROM texts WHERE text_hash=?',(item['hash'],)).fetchone()
        if current and current['language'] is not None:
            cx.execute('UPDATE texts SET topic_status=?,topics_json=? WHERE text_hash=?',(item['status'],item['weights'],item['hash']))
            assignments+=1
            if assignments%10000==0: cx.commit()
    for item in original.execute('SELECT hash,vector,chunks FROM embeddings'):
        if cx.execute('SELECT 1 FROM texts WHERE text_hash=?',(item['hash'],)).fetchone():
            cx.execute('INSERT OR IGNORE INTO embeddings VALUES (?,?,?)',tuple(item)); vectors+=1
            if vectors%5000==0: cx.commit()
    original.close()
    meta_set(cx,'cache_reused',dict(nlp_texts=count,topic_assignments=assignments,embeddings=vectors))
    cx.commit(); atomic_json(WORK/'reutilizacion.json',meta_get(cx,'cache_reused'))
    progress.update('cache_reutilizada',count,None,'Predicciones originales copiadas, nunca modificadas',topic_assignments=assignments,embeddings=vectors)


def sentiment(cx,progress):
    from nlp import infer
    from models import OnnxSentiment
    packages={name:importlib.metadata.version(name) for name in meta_get(cx,'packages_original')}
    if packages!=meta_get(cx,'packages_original'): raise ValueError('Versiones de sentimiento distintas; no mezclar caché')
    model=OnnxSentiment('xlm_t',threads=4,batch_size=32,progress=progress)
    if [model.manifest]!=meta_get(cx,'sentiment_models_original'):
        raise ValueError('Modelo de sentimiento no coincide con caché')
    meta_set(cx,'packages_sentiment',packages); cx.commit()
    complete=infer(cx,progress,stopped,'xlm_t',{'xlm_t':model})
    if complete: meta_set(cx,'sentiment_done',True); cx.commit()


def topics(cx,progress):
    if cx.execute('SELECT count(*) FROM texts WHERE nlp_status IS NULL').fetchone()[0]:
        raise ValueError('Completar idioma/sentimiento antes de inferir tópicos')
    info=meta_get(cx,'topic_model')
    packages={name:importlib.metadata.version(name) for name in info['environment']}
    if packages!=info['environment']: raise ValueError('Versiones de tópicos incompatibles; no actualizar ni reentrenar')
    if digest(TOPIC/'model_v2.joblib')!=meta_get(cx,'topic_model_file_sha256'): raise ValueError('Modelo modificado')
    configuration=dict(model=info['version'],sha256=info['sha256'],languages=['es','xx'],
                       min_words=4,batch=256,order='text_hash',policy='cache_original_then_new_sorted_hash_v1')
    if meta_get(cx,'topic_configuration') not in (None,configuration): raise ValueError('Política temática cambió')
    meta_set(cx,'topic_configuration',configuration); cx.commit()
    import joblib
    sys.path.insert(0,str(REPO/'repos_wrapper/topicos_comparacion'))
    from experiment import predict, eligibility
    artifact=joblib.load(TOPIC/'model_v2.joblib')
    encoder=None; total=cx.execute('select count(*) from texts').fetchone()[0]
    while True:
        batch=cx.execute('SELECT text_hash,text,language FROM texts WHERE topic_status IS NULL ORDER BY text_hash LIMIT 256').fetchall()
        if not batch: break
        eligible=[(r['text_hash'],r['text']) for r in batch if eligibility(r['text'],r['language']) is None]
        predicted,encoder=predict(artifact,info,eligible,cx,progress,stopped,encoder) if eligible else ([],encoder)
        lookup=dict(zip((h for h,_ in eligible),predicted))
        for item in batch:
            status,weights=lookup.get(item['text_hash'],(eligibility(item['text'],item['language']),[]))
            if status=='OK' and item['language']=='xx': status='OK_IDIOMA_INCIERTO'
            cx.execute('UPDATE texts SET topic_status=?,topics_json=? WHERE text_hash=?',
                       (status,json.dumps(weights),item['text_hash']))
        cx.commit()
        done=cx.execute('SELECT count(*) FROM texts WHERE topic_status IS NOT NULL').fetchone()[0]
        progress.update('topicos_41',done,total,'Modelo original fijo, sin entrenamiento nuevo')
        if stopped(): return
    meta_set(cx,'topics_done',True); meta_set(cx,'packages_topics',packages); cx.commit()


def export(cx,progress,partial=False):
    pending=cx.execute('SELECT count(*) FROM texts WHERE nlp_status IS NULL OR topic_status IS NULL').fetchone()[0]
    if pending and not partial: raise ValueError('NLP/tópicos pendientes; no exportar como terminado')
    folder=WORK/('fase1' if partial else 'final'); folder.mkdir(parents=True,exist_ok=True)
    outputs=[]
    topic_version=meta_get(cx,'topic_model')['version']
    def write(name,fields,records):
        target=folder/name; temp=target.with_suffix('.csv.tmp'); count=0
        with temp.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n'); writer.writeheader()
            for row in records:
                writer.writerow(row); count+=1
                if count%100000==0: progress.update('exportar_'+name,count,None,'Salida temporal')
            stream.flush(); os.fsync(stream.fileno())
        read_count=sum(1 for _ in rows(temp))
        if count!=read_count: raise ValueError('Exportación no concilia')
        temp.replace(target)
        outputs.append(dict(file=name,rows=count,bytes=target.stat().st_size,sha256=digest(target)))
        return count
    places={r['place_key']:json.loads(r['raw_json']) for r in cx.execute('SELECT place_key,raw_json FROM places')}
    pcols=list(dict.fromkeys(k for row in places.values() for k in row))
    pf=['codigo_pais','pais','pais_iso3','clave_lugar']+pcols+['banderas_calidad','archivo_origen','registro_origen','fecha_observacion_reputacion','precision_observacion_reputacion']
    def place_records():
        for r in cx.execute('SELECT p.*,q.flags FROM places p JOIN place_quality q USING(place_key) ORDER BY p.place_key'):
            row=json.loads(r['raw_json']); name,iso=COUNTRIES[r['country']]
            yield dict(codigo_pais=r['country'],pais=name,pais_iso3=iso,clave_lugar=r['place_key'],**row,
                banderas_calidad=r['flags'],archivo_origen=r['source'],registro_origen=r['line'],
                fecha_observacion_reputacion='',precision_observacion_reputacion='NO_DOCUMENTADA')
    write('base_madre_lugares.csv',pf,place_records())
    derived=['codigo_pais','pais','pais_iso3','clave_lugar','corrida_fuente','registro_completo_fuente','pais_fuente','banderas_calidad',
        'categoria_museo_incluida','categoria_museo_exacta','hash_texto_nlp','codigo_idioma','confianza_idioma','metodo_idioma',
        'sentimiento','puntaje_sentimiento','confianza_sentimiento','p_negativo','p_neutro','p_positivo','version_modelo_sentimiento',
        'numero_tokens','ventanas_texto','estado_nlp','estado_topicos','topico_dominante','version_modelo_topicos',
        'asignacion_topico_es_probabilidad','archivo_origen','registro_origen']
    def review_records():
        for item in cx.execute('SELECT r.*,q.flags,t.* FROM reviews r JOIN texts t USING(text_hash) JOIN review_quality q USING(review_id) ORDER BY r.review_id'):
            raw=json.loads(item['raw_json']); country=item['country']; name,iso=COUNTRIES[country]
            weights=json.loads(item['topics_json'] or '[]')
            out={k:raw[k] for k in REVIEW_FIELDS}
            out.update({'museo_'+k:places.get(item['place_key'],{}).get(k,'') for k in pcols})
            derivation_input=dict(raw)
            try: integer(raw['n_review_user'])
            except (ValueError,OverflowError): derivation_input['n_review_user']=''
            # La copia de derivación admite historial desconocido. El valor crudo
            # original se conserva intacto y la incidencia sigue en banderas_calidad.
            try: out.update(segments(derivation_input,places.get(item['place_key'],{})))
            except (ValueError,OverflowError):
                out.update({k:'' for k in DERIVED})
                out['precision_fecha_resena']='NO_DERIVABLE_REVISAR_BANDERAS'
            out.update(codigo_pais=country,pais=name,pais_iso3=iso,clave_lugar=item['place_key'],
                corrida_fuente=raw.get('corrida',''),registro_completo_fuente=raw.get('registro_completo',''),pais_fuente=raw.get('pais',''),
                banderas_calidad=item['flags'],categoria_museo_incluida=int(museum(raw['categoria_google'])),categoria_museo_exacta=int(raw['categoria_google']=='Museo'),
                hash_texto_nlp=item['text_hash'],codigo_idioma=item['language'] or '',confianza_idioma=item['language_score'],metodo_idioma=item['language_engine'],
                sentimiento=item['sentiment'] or '',puntaje_sentimiento=item['sentiment_score'],confianza_sentimiento=item['confidence'],
                p_negativo=item['p_negative'],p_neutro=item['p_neutral'],p_positivo=item['p_positive'],version_modelo_sentimiento=item['sentiment_model'],
                numero_tokens=item['tokens'],ventanas_texto=item['chunks'],estado_nlp=item['nlp_status'] or 'PENDIENTE',estado_topicos=item['topic_status'] or 'PENDIENTE',
                topico_dominante=weights[0][0] if weights else '',version_modelo_topicos=topic_version,
                asignacion_topico_es_probabilidad=0,archivo_origen=item['source'],registro_origen=item['line'])
            yield out
    count=write('base_madre_resenas.csv',REVIEW_FIELDS+['museo_'+k for k in pcols]+DERIVED+derived,review_records())
    if count!=cx.execute('select count(*) from reviews').fetchone()[0]: raise ValueError('Se perdieron/multiplicaron reseñas')
    catalog=list(rows(OLD/'final/S-BERT/catalogo_dimensiones_latentes.csv'))
    write('catalogo_dimensiones_latentes.csv',list(catalog[0][1]),(r for _,r in catalog))
    codes={r['codigo_topico'] for _,r in catalog}
    def bridges():
        for row in cx.execute('SELECT r.review_id,t.topics_json FROM reviews r JOIN texts t USING(text_hash) WHERE t.topics_json IS NOT NULL'):
            weights=json.loads(row['topics_json'])
            if len(weights)>1: raise ValueError('La línea base no admite mezcla de tópicos')
            for code,weight in weights:
                if code not in codes or weight!=1.: raise ValueError('Tópico/peso inválido')
                yield dict(id_review=row['review_id'],codigo_topico=code,peso=1,es_dominante=1,version_modelo=topic_version)
    write('resena_dimension_latente.csv',['id_review','codigo_topico','peso','es_dominante','version_modelo'],bridges())
    report=summary(cx)
    coverage=[]
    for country,stats in report['countries'].items():
        coverage.append(dict(codigo_pais=country,resenas=stats['reviews'],con_texto=stats['with_text'],
            elegibles_linea_base=stats['eligible_topics'],asignadas=stats['assigned'],
            cobertura_sobre_con_texto=stats['assigned']/stats['with_text'] if stats['with_text'] else '',
            cobertura_sobre_elegibles=stats['assigned']/stats['eligible_topics'] if stats['eligible_topics'] else '',
            pendientes=stats['topics'].get('PENDIENTE',0),validacion_humana='PENDIENTE'))
    write('cobertura_por_pais.csv',list(coverage[0]),coverage)
    def distributions():
        for country,code,n in cx.execute("SELECT r.country,json_extract(t.topics_json,'$[0][0]'),count(*) FROM reviews r JOIN texts t USING(text_hash) WHERE t.topic_status IN ('OK','OK_IDIOMA_INCIERTO') GROUP BY 1,2 ORDER BY 1,3 DESC"):
            yield dict(codigo_pais=country,codigo_topico=code,resenas=n,version_modelo=topic_version)
    write('distribucion_topicos_por_pais.csv',['codigo_pais','codigo_topico','resenas','version_modelo'],distributions())
    report.update(state='FASE1_NLP_PENDIENTE' if pending else 'COMPLETADO_TECNICAMENTE',outputs=outputs,
        human_validation='PENDIENTE; no se rellenaron anotaciones humanas',
        baseline_topic_languages=['es','xx'],sentiment_languages=['ar','en','fr','de','hi','it','es','pt'],
        limitations=['No prueba precisión humana ni exhaustividad del scraping.',
          'Tópicos es/xx: otros idiomas conservados sin forzar a los 41 tópicos.',
          'xx significa incierto, no idioma soportado demostrado.',
          'Peso 1 indica pertenencia, no probabilidad calibrada.',
          'Nombres de los tópicos propuestos por IA, pendientes de revisión.',
          'La mezcla de categorías y sesgo de reseñadores limita comparaciones de países.'])
    atomic_json(folder/'validacion_final.json',report)
    lines=['# Ampliación PE, MX y AR', '', f"Estado: {report['state']}.",
        f"Actualizado: {report['updated']} (UTC).", '',
        'La validación humana sigue pendiente. Esta salida no demuestra exactitud del modelo.', '',
        '| País | Reseñas | Con texto | Elegibles para los 41 tópicos | Asignadas |',
        '|---|---:|---:|---:|---:|']
    for country,stats in report['countries'].items():
        lines.append(f"| {country} | {stats['reviews']:,} | {stats['with_text']:,} | {stats['eligible_topics']:,} | {stats['assigned']:,} |")
    lines.extend(['',f"Textos únicos pendientes de idioma/sentimiento: {report['pending_unique_nlp']:,}.",
                  f"Textos únicos pendientes de tópicos: {report['pending_unique_topics']:,}.",'',
        'Se conservan todos los idiomas. El sentimiento tiene un alcance multilingüe definido; los 41 tópicos mantienen su alcance anterior español/idioma incierto y mínimo de cuatro palabras.', '',
        'No se entrenó un modelo nuevo. Se conservaron los 41 códigos y las etiquetas propuestas del catálogo anterior.', '',
        'Revisar cobertura_por_pais.csv y distribucion_topicos_por_pais.csv. Los conteos reflejan reseñas recolectadas, no una muestra representativa de todos los visitantes.', '',
        'Las bases y el puente están en esta carpeta. La base de reseñas supera el límite de filas de una hoja Excel: usar SQL, Power Query o lectura por bloques.', '',
        'Los informes de auditoría, fuentes y reutilización están en la carpeta superior. Las fuentes y checkpoints anteriores no fueron sobrescritos.'])
    temp=folder/'RESUMEN.md.tmp'; temp.write_text('\n'.join(lines)+'\n',encoding='utf-8'); temp.replace(folder/'RESUMEN.md')
    progress.update(report['state'],count,count,'Exportación conciliada; validación humana pendiente')


def summary(cx):
    result=dict(version=VERSION,updated=utcnow(),cache=meta_get(cx,'cache_reused'),countries={})
    for country in COUNTRIES:
        nlp=dict(cx.execute('SELECT COALESCE(t.nlp_status,\'PENDIENTE\'),count(*) FROM reviews r JOIN texts t USING(text_hash) WHERE r.country=? GROUP BY t.nlp_status',(country,)).fetchall())
        topic=dict(cx.execute('SELECT COALESCE(t.topic_status,\'PENDIENTE\'),count(*) FROM reviews r JOIN texts t USING(text_hash) WHERE r.country=? GROUP BY t.topic_status',(country,)).fetchall())
        langs=dict(cx.execute('SELECT COALESCE(t.language,\'PENDIENTE\'),count(*) FROM reviews r JOIN texts t USING(text_hash) WHERE r.country=? GROUP BY t.language',(country,)).fetchall())
        assigned=sum(n for s,n in topic.items() if s in ('OK','OK_IDIOMA_INCIERTO'))
        with_text=cx.execute("SELECT count(*) FROM reviews r JOIN texts t USING(text_hash) WHERE r.country=? AND t.text<>''",(country,)).fetchone()[0]
        eligible=cx.execute("SELECT count(*) FROM reviews r JOIN texts t USING(text_hash) WHERE r.country=? AND t.language IN ('es','xx') AND t.text<>'' AND length(t.text)-length(replace(t.text,' ',''))+1>=4",(country,)).fetchone()[0]
        result['countries'][country]=dict(reviews=sum(topic.values()),with_text=with_text,eligible_topics=eligible,nlp=nlp,topics=topic,languages=langs,assigned=assigned)
    result['pending_unique_nlp']=cx.execute('select count(*) from texts where nlp_status IS NULL').fetchone()[0]
    result['pending_unique_topics']=cx.execute('select count(*) from texts where topic_status IS NULL').fetchone()[0]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['preparar','conciliar','sentimiento','topicos','exportar','estado','detener'])
    parser.add_argument('--parcial',action='store_true')
    parser.add_argument('--detallado',action='store_true',help='Solo estado y con corrida detenida: consultar SQLite')
    args=parser.parse_args()
    WORK.mkdir(parents=True,exist_ok=True)
    if args.command=='detener':
        atomic_json(STOP,dict(requested=utcnow(),action='parada segura al terminar el lote'))
        print('Parada solicitada. Se conserva el checkpoint.'); return
    if args.command=='estado':
        if args.detallado:
            lock=ProcessLock(WORK/'process.lock')
            try:
                cx=ro(WORK/'checkpoint.sqlite')
                try: value=summary(cx)
                finally: cx.close()
            finally: lock.close()
        else:
            value={'mode':'SNAPSHOTS_SIN_CONSULTAR_SQLITE','consulted_at':utcnow()}
            for name in ('supervisor','progreso','checkpoint_confirmado','bloqueo_sqlite','estado_resumen'):
                path=WORK/(name+'.json')
                if path.exists(): value[name]=json.loads(path.read_text(encoding='utf-8'))
            value['note']='estado_resumen es la última fase terminada; progreso/checkpoint_confirmado muestran avances actuales'
        print(json.dumps(value,ensure_ascii=False,indent=2)); return
    lock=ProcessLock(WORK/'process.lock'); progress=Progress(); cx=connect(WORK/'checkpoint.sqlite')
    cx.executescript('''CREATE TABLE IF NOT EXISTS review_quality(review_id TEXT PRIMARY KEY,flags TEXT NOT NULL,content_hash TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS place_quality(place_key TEXT PRIMARY KEY,flags TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS duplicate_sources(review_id TEXT NOT NULL,source TEXT NOT NULL,line INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS argentina_raw_check(review_id TEXT PRIMARY KEY,content_hash TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS embeddings(hash TEXT PRIMARY KEY,vector BLOB NOT NULL,chunks INTEGER NOT NULL);
      CREATE INDEX IF NOT EXISTS ix_reviews_country_text ON reviews(country,text_hash);
      CREATE INDEX IF NOT EXISTS ix_topics_pending_hash ON texts(topic_status,text_hash);''')
    try:
        if stopped(): raise InterruptedError('Existe stop.request: revisar antes de reanudar')
        if args.command=='preparar':
            prepare(cx,progress)
            if meta_get(cx,'prepared') and not stopped(): reuse(cx,progress)
        else:
            if not meta_get(cx,'prepared') or not meta_get(cx,'cache_reused'): raise ValueError('Preparar primero')
            if args.command=='conciliar': reconcile_previous(cx)
            elif args.command=='sentimiento': sentiment(cx,progress)
            elif args.command=='topicos': topics(cx,progress)
            elif args.command=='exportar': export(cx,progress,args.parcial)
        atomic_json(WORK/'estado_resumen.json',summary(cx))
    except Exception as exc:
        cx.rollback(); progress.update('ERROR',message=str(exc)); raise
    finally:
        cx.close(); lock.close()


if __name__=='__main__': main()
