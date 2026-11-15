"""Fase 1: unificación auditable; jamás modifica los CSV nacionales."""
import csv
import heapq
import json
import math
from collections import Counter
from pathlib import Path

from common import (REPO,SOURCES,REVIEW_FIELDS,VERSION,digest,read_csv,iso_date,integer,
                    normalized_text,text_key,meta_get,meta_set,segments,presence,atomic_json)


def source_manifest():
    result=[]
    for country,name,iso3,base,reviews in SOURCES:
        for kind,folder,filename in [('places','lugares',base),('reviews','resenas',reviews)]:
            path=REPO/'data'/folder/filename
            if not path.is_file():
                raise FileNotFoundError(f'Falta fuente completa: {path}. No se usa la muestra de 5 000.')
            with path.open(encoding='utf-8-sig',newline='') as f:
                columns=next(csv.reader(f))
            if kind=='reviews' and columns!=REVIEW_FIELDS:
                raise ValueError(f'Contrato de reseñas incompatible: {path}')
            result.append(dict(country=country,kind=kind,path=str(path.relative_to(REPO)),
                               size=path.stat().st_size,sha256=digest(path),columns=columns))
    return result


def distance(a,b):
    la1,la2=map(math.radians,[float(a['lat']),float(b['lat'])])
    dl=math.radians(float(a['lon'])-float(b['lon']))
    x=math.sin((la1-la2)/2)**2+math.cos(la1)*math.cos(la2)*math.sin(dl/2)**2
    return 2*6371*math.asin(min(1,math.sqrt(x)))


def priority(row):
    return (bool(row['caption'].strip()),len(row['caption']),
            sum(bool(v.strip()) for v in row.values()),iso_date(row['retrieval_date']),row['google_place_id'])


def sample_rows(source,progress,per_stratum=100):
    heaps={}
    for line,row in read_csv(REPO/source['path']):
        rating=str(int(float(row['rating'])))
        heap=heaps.setdefault(rating,[])
        rank=int(text_key(source['country']+':'+row['id_review']+':'+str(line)),16)
        item=(-rank,line,row)
        if len(heap)<per_stratum: heapq.heappush(heap,item)
        elif item[0]>heap[0][0]: heapq.heapreplace(heap,item)
        if line%50000==0:
            progress.update('muestreo_piloto',line,0,f"Seleccionando por país y estrellas: {source['country']}")
    return sorted((line,row) for heap in heaps.values() for _,line,row in heap)


def prepare(cx,mode,progress,stop_requested):
    progress.update('verificar_fuentes',0,4,'Calculando hashes de las cuatro fuentes')
    manifest=source_manifest()
    spec=dict(version=VERSION,mode=mode,sources=manifest,dedup='texto_mas_completo_reciente_place_id_v1')
    old=meta_get(cx,'input_spec')
    if old and old!=spec:
        raise ValueError('Las fuentes o el contrato cambiaron. Usa otro directorio de trabajo; no se mezclan checkpoints.')
    meta_set(cx,'input_spec',spec)
    cx.commit()
    if meta_get(cx,'phase1_done',False):
        progress.update('fase1_verificada',cx.execute('SELECT COUNT(*) FROM reviews').fetchone()[0],0,'Checkpoint de fase 1 reutilizado')
        return manifest
    for source in [s for s in manifest if s['kind']=='places']:
        if meta_get(cx,'places_done:'+source['country'],False): continue
        count=0
        for line,row in read_csv(REPO/source['path']):
            if list(row)!=source['columns'] or not row['id'] or row['category']!='Museo':
                raise ValueError(f"Museo inválido: {source['path']}:{line}")
            if not (-90<=float(row['lat'])<=90 and -180<=float(row['lon'])<=180):
                raise ValueError('Coordenadas fuera de rango')
            key=source['country']+':'+row['id']
            cx.execute('INSERT INTO places VALUES (?,?,?,?,?,?)',
                       (key,source['country'],row['id'],json.dumps(row,ensure_ascii=False,separators=(',',':')),source['path'],line))
            count+=1
        meta_set(cx,'places_done:'+source['country'],True)
        cx.commit()
        progress.update('unificar_lugares',count,0,source['country'])
    places={r['place_key']:json.loads(r['raw_json']) for r in cx.execute('SELECT * FROM places')}
    for source in [s for s in manifest if s['kind']=='reviews']:
        country=source['country']
        if meta_get(cx,'reviews_done:'+country,False): continue
        last=meta_get(cx,'review_cursor:'+country,0)
        iterable=sample_rows(source,progress) if mode=='piloto' else read_csv(REPO/source['path'])
        count=meta_get(cx,'rows_read:'+country,0)
        for line,row in iterable:
            if line<=last: continue
            review_id=row['id_review']
            place_key=country+':'+row['google_place_id']
            if not review_id.strip() or place_key not in places or row['categoria_google']!='Museo':
                raise ValueError(f"Clave/unión inválida: {source['path']}:{line}")
            if float(row['rating']) not in (1,2,3,4,5): raise ValueError('Rating inválido')
            if iso_date(row['review_date'])>iso_date(row['retrieval_date']): raise ValueError('Fechas incoherentes')
            integer(row['n_review_user'])
            payload=json.dumps(row,ensure_ascii=False,separators=(',',':'))
            previous=cx.execute('SELECT * FROM reviews WHERE review_id=?',(review_id,)).fetchone()
            if previous:
                previous_row=json.loads(previous['raw_json'])
                km=distance(places[previous['place_key']],places[place_key])
                if previous['country']!=country or float(previous_row['rating'])!=float(row['rating']) or km>1:
                    raise ValueError(f'Colisión de ID no resoluble automáticamente: {review_id}; distancia={km:.3f}km')
                if priority(row)>priority(previous_row):
                    loser,loser_place,loser_source,loser_line=previous['raw_json'],previous['place_key'],previous['source'],previous['line']
                    cx.execute('UPDATE reviews SET place_key=?,raw_json=?,text_hash=?,source=?,line=? WHERE review_id=?',
                               (place_key,payload,text_key(row['caption']),source['path'],line,review_id))
                else:
                    loser,loser_place,loser_source,loser_line=payload,place_key,source['path'],line
                cx.execute('INSERT INTO duplicates(review_id,discarded_place,raw_json,source,line,distance_km,reason) VALUES (?,?,?,?,?,?,?)',
                           (review_id,loser_place,loser,loser_source,loser_line,km,spec['dedup']))
            else:
                cx.execute('INSERT INTO reviews VALUES (?,?,?,?,?,?,?)',
                           (review_id,country,place_key,payload,text_key(row['caption']),source['path'],line))
            count+=1
            if count%3000==0:
                meta_set(cx,'review_cursor:'+country,line)
                meta_set(cx,'rows_read:'+country,count)
                cx.commit()
                progress.update('unificar_resenas',count,0,f'{country}; checkpoint confirmado')
                if stop_requested(): return None
        meta_set(cx,'rows_read:'+country,count)
        meta_set(cx,'reviews_done:'+country,True)
        cx.commit()
        progress.update('unificar_resenas',count,count,country)
        if stop_requested(): return None
    # Solo se insertan textos CANÓNICOS tras resolver todos los duplicados.
    for i,row in enumerate(cx.execute('SELECT raw_json,text_hash FROM reviews'),1):
        text=normalized_text(json.loads(row['raw_json'])['caption'])
        cx.execute('INSERT OR IGNORE INTO texts(text_hash,text) VALUES (?,?)',(row['text_hash'],text))
        if i%10000==0:
            cx.commit()
            progress.update('indexar_textos_unicos',i,0,'No se repite inferencia sobre textos idénticos')
            if stop_requested(): return None
    count=cx.execute('SELECT COUNT(*) FROM reviews').fetchone()[0]
    read_count=sum(meta_get(cx,'rows_read:'+s[0],0) for s in SOURCES)
    duplicates=cx.execute('SELECT COUNT(*) FROM duplicates').fetchone()[0]
    if count+duplicates!=read_count: raise ValueError('La conciliación de filas de origen falló')
    if mode=='completo' and count<500000: raise ValueError('El corpus completo no alcanza 500 mil reseñas; no se publica como completo')
    meta_set(cx,'phase1_done',True)
    meta_set(cx,'counts',dict(rows_input=read_count,reviews=count,duplicates=duplicates,
                           places=len(places),unique_texts=cx.execute("SELECT COUNT(*) FROM texts WHERE text<>''").fetchone()[0]))
    cx.commit()
    progress.update('fase1_completa',count,count,f'{duplicates} variantes conservadas en auditoría')
    return manifest


DERIVED=['cantidad_palabras','tiene_texto','n_resenas_autor_asof','segmento_perfil_autor',
         'segmento_extension','fecha_estimada_analitica','precision_fecha_resena','periodo_codigo',
         'segmento_antiguedad','segmento_presencia_digital']
NLP_FIELDS=['codigo_idioma','confianza_idioma','metodo_idioma','sentimiento','puntaje_sentimiento',
            'confianza_sentimiento','p_negativo','p_neutro','p_positivo','version_modelo_sentimiento',
            'estado_nlp','numero_tokens','ventanas_texto','estado_topicos','topico_dominante','version_modelo_topicos']


def export(cx,folder,progress,allow_pending=False):
    folder.mkdir(parents=True,exist_ok=True)
    spec=meta_get(cx,'input_spec')
    if not spec or not meta_get(cx,'phase1_done',False): raise ValueError('Fase 1 todavía incompleta')
    pending=cx.execute('SELECT COUNT(*) FROM texts WHERE nlp_status IS NULL').fetchone()[0]
    if pending and not allow_pending: raise ValueError(f'NLP pendiente en {pending} textos: no se publica como final')
    place_columns=spec['sources'][0]['columns']
    if any(s['columns']!=place_columns for s in spec['sources'] if s['kind']=='places'):
        raise ValueError('Las bases de lugares no tienen el mismo contrato')
    places={r['place_key']:dict(r) for r in cx.execute('SELECT * FROM places')}
    country_info={c:(name,iso3) for c,name,iso3,_,_ in SOURCES}
    place_counts=dict(cx.execute('SELECT place_key,COUNT(*) FROM reviews GROUP BY place_key').fetchall())
    output_info=[]
    def write(name,columns,records):
        dest=folder/name; temp=dest.with_suffix('.csv.tmp'); count=0
        with temp.open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=columns,lineterminator='\n',extrasaction='raise')
            writer.writeheader()
            for record in records:
                writer.writerow(record); count+=1
                if count%10000==0: progress.update('exportar_'+name,count,0,'Salida temporal: el archivo vigente aún no cambia')
        # Lectura independiente para detectar CSV incompleto o truncado.
        read_count=sum(1 for _ in read_csv(temp))
        if count!=read_count: raise ValueError(f'CSV no reconciliado: {name}')
        temp.replace(dest)
        output_info.append(dict(file=name,rows=count,sha256=digest(dest),bytes=dest.stat().st_size))
        return count
    def place_records():
        for key,item in sorted(places.items()):
            row=json.loads(item['raw_json']); country=item['country']; name,iso3=country_info[country]
            yield dict(pais=name,codigo_pais=country,pais_iso3=iso3,**row,
                segmento_presencia_digital=presence(row),n_resenas_extraidas=place_counts.get(key,0),
                fecha_observacion_reputacion='',precision_observacion_reputacion='NO_DOCUMENTADA',
                archivo_origen=item['source'],registro_origen=item['line'])
    place_fields=['pais','codigo_pais','pais_iso3']+place_columns+['segmento_presencia_digital','n_resenas_extraidas',
        'fecha_observacion_reputacion','precision_observacion_reputacion','archivo_origen','registro_origen']
    write('base_madre_lugares.csv',place_fields,place_records())
    topic_meta=meta_get(cx,'topic_catalog',[])
    topic_version=meta_get(cx,'topic_version','')
    def review_records():
        query='''SELECT r.*,t.language,t.language_score,t.language_engine,t.sentiment,t.sentiment_score,t.confidence,
                 t.p_negative,t.p_neutral,t.p_positive,t.sentiment_model,t.tokens,t.chunks,t.nlp_status,t.topic_status,t.topics_json
                 FROM reviews r JOIN texts t ON r.text_hash=t.text_hash ORDER BY r.review_id'''
        for item in cx.execute(query):
            row=json.loads(item['raw_json']); place=json.loads(places[item['place_key']]['raw_json'])
            country=item['country']; name,iso3=country_info[country]
            topics=json.loads(item['topics_json'] or '[]')
            dominant=max(topics,key=lambda x:x[1])[0] if topics else ''
            nlp=dict(codigo_idioma=item['language'] or 'xx',confianza_idioma=item['language_score'],
                metodo_idioma=item['language_engine'],sentimiento=item['sentiment'] or ('SIN_TEXTO' if not row['caption'].strip() else 'NO_CLASIFICADO'),
                puntaje_sentimiento=item['sentiment_score'],confianza_sentimiento=item['confidence'],
                p_negativo=item['p_negative'],p_neutro=item['p_neutral'],p_positivo=item['p_positive'],
                version_modelo_sentimiento=item['sentiment_model'],estado_nlp=item['nlp_status'] or 'PENDIENTE',
                numero_tokens=item['tokens'],ventanas_texto=item['chunks'],estado_topicos=item['topic_status'] or 'PENDIENTE',
                topico_dominante=dominant,version_modelo_topicos=topic_version)
            yield dict(pais=name,codigo_pais=country,pais_iso3=iso3,**row,
                **{'museo_'+k:place[k] for k in place_columns},**segments(row,place),**nlp,
                hash_texto_nlp=item['text_hash'],archivo_origen=item['source'],registro_origen=item['line'])
    review_fields=['pais','codigo_pais','pais_iso3']+REVIEW_FIELDS+['museo_'+k for k in place_columns]+DERIVED+NLP_FIELDS+['hash_texto_nlp','archivo_origen','registro_origen']
    count=write('base_madre_resenas.csv',review_fields,review_records())
    if count!=cx.execute('SELECT COUNT(*) FROM reviews').fetchone()[0]: raise ValueError('La unión multiplicó o perdió reseñas')
    catalog_fields=['codigo_topico','idioma','etiqueta','descripcion','palabras_clave','version_modelo','metodo','validacion_etiqueta']
    write('catalogo_dimensiones_latentes.csv',catalog_fields,topic_meta)
    def topic_records():
        for item in cx.execute('SELECT r.review_id,t.topics_json FROM reviews r JOIN texts t ON r.text_hash=t.text_hash WHERE t.topics_json IS NOT NULL ORDER BY r.review_id'):
            assignments=json.loads(item['topics_json'])
            if not assignments: continue
            if abs(sum(float(weight) for _,weight in assignments)-1)>1e-6: raise ValueError('Pesos no suman 1')
            dominant=max(assignments,key=lambda x:x[1])[0]
            for code,weight in assignments:
                yield dict(id_review=item['review_id'],codigo_topico=code,peso=format(weight,'.9f'),
                           es_dominante=int(code==dominant),version_modelo=topic_version)
    write('resena_dimension_latente.csv',['id_review','codigo_topico','peso','es_dominante','version_modelo'],topic_records())
    def duplicate_records():
        for d in cx.execute('SELECT d.*,r.place_key chosen FROM duplicates d JOIN reviews r USING(review_id) ORDER BY d.id'):
            row=json.loads(d['raw_json'])
            yield dict(**row,place_key_conservado=d['chosen'],archivo_origen=d['source'],registro_origen=d['line'],
                       distancia_km=d['distance_km'],regla=d['reason'])
    write('auditoria_duplicados.csv',REVIEW_FIELDS+['place_key_conservado','archivo_origen','registro_origen','distancia_km','regla'],duplicate_records())
    report=dict(version=VERSION,mode=spec['mode'],estado='FASE1_NLP_PENDIENTE' if pending else 'EXPORTADO',
                counts=meta_get(cx,'counts'),sources=spec['sources'],outputs=output_info,
                nlp_status=dict(cx.execute('SELECT nlp_status,COUNT(*) FROM texts GROUP BY nlp_status').fetchall()),
                modelos_sentimiento=meta_get(cx,'sentiment_models',[]),modelo_topicos=meta_get(cx,'topic_manifest',{}),
                limitations=['Reputación sin fecha de observación documentada.',
                              'Tópicos separados por idioma; no asumir equivalencia entre códigos de distintos idiomas.',
                              'Etiquetas y calidad semántica requieren revisión independiente del equipo.'])
    atomic_json(folder/'validacion_final.json',report)
    return report
