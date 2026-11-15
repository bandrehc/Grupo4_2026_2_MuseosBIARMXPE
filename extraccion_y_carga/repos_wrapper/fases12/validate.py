"""Lectura independiente de archivos finales: PK, FK, cardinalidad y medidas."""
import json
import math
from collections import Counter,defaultdict
from common import read_csv,REVIEW_FIELDS,digest,iso_date,integer,atomic_json

def validate(folder,allow_pending=False):
    report=json.loads((folder/'validacion_final.json').read_text(encoding='utf-8'))
    places={}; reviews={}; statuses=Counter(); with_text=0
    for output in report['outputs']:
        path=folder/output['file']
        with path.open('rb') as f:
            if f.read(3)!=b'\xef\xbb\xbf': raise ValueError('CSV sin BOM UTF-8: '+path.name)
        if digest(path)!=output['sha256']: raise ValueError('Hash de salida modificado: '+path.name)
        if sum(1 for _ in read_csv(path))!=output['rows']: raise ValueError('Conteo distinto: '+path.name)
    for _,r in read_csv(folder/'base_madre_lugares.csv'):
        key=(r['codigo_pais'],r['id'])
        if key in places: raise ValueError('PK de museo repetida')
        places[key]=int(r['n_resenas_extraidas'])
        if r['fecha_observacion_reputacion'] or r['precision_observacion_reputacion']!='NO_DOCUMENTADA':
            raise ValueError('Se inventó una fecha de observación')
    actual_counts=Counter()
    for _,r in read_csv(folder/'base_madre_resenas.csv'):
        uid=r['id_review']; key=(r['codigo_pais'],r['google_place_id'])
        if uid in reviews or key not in places: raise ValueError('PK/FK de reseña inválida')
        if r['google_place_id']!=r['museo_id']: raise ValueError('Unión con museo incorrecta')
        for field in REVIEW_FIELDS:
            if field not in r: raise ValueError('Se perdió columna original: '+field)
        if float(r['rating']) not in (1,2,3,4,5): raise ValueError('Rating inválido')
        if int(r['cantidad_palabras'])!=len(r['caption'].split()): raise ValueError('Conteo de palabras incorrecto')
        if bool(int(r['tiene_texto']))!=bool(r['caption'].strip()): raise ValueError('Bandera texto incorrecta')
        if iso_date(r['review_date'])>iso_date(r['retrieval_date']): raise ValueError('Fecha de origen incoherente')
        if r['fecha_estimada_analitica'] and iso_date(r['fecha_estimada_analitica'])>iso_date(r['retrieval_date']):
            raise ValueError('Fecha analítica futura')
        integer(r['n_review_user'])
        probs=[r['p_negativo'],r['p_neutro'],r['p_positivo']]
        if any(probs):
            p=[float(x) for x in probs]
            if any(not math.isfinite(x) or not 0<=x<=1 for x in p) or abs(sum(p)-1)>1e-5:
                raise ValueError('Probabilidades NLP inválidas')
            if abs(float(r['puntaje_sentimiento'])-(p[2]-p[0]))>1e-6: raise ValueError('Puntaje distinto de Ppos-Pneg')
        elif r['sentimiento'] not in ('NO_CLASIFICADO','SIN_TEXTO'): raise ValueError('Etiqueta sin evidencia probabilística')
        if not allow_pending and (r['estado_nlp']=='PENDIENTE' or r['estado_topicos']=='PENDIENTE'):
            raise ValueError('Fase 2 todavía incompleta')
        reviews[uid]=r['topico_dominante']
        statuses[r['estado_nlp']]+=1; with_text+=int(r['tiene_texto']); actual_counts[key]+=1
    if len(reviews)!=report['counts']['reviews'] or len(places)!=report['counts']['places']:
        raise ValueError('Cardinalidad incompatible con checkpoint')
    if any(actual_counts[key]!=expected for key,expected in places.items()): raise ValueError('Conteo por lugar incorrecto')
    catalog=set()
    for _,r in read_csv(folder/'catalogo_dimensiones_latentes.csv'):
        if r['codigo_topico'] in catalog: raise ValueError('PK de tópico repetida')
        catalog.add(r['codigo_topico'])
    pairs=set(); sums=defaultdict(float); dominants=Counter()
    for _,r in read_csv(folder/'resena_dimension_latente.csv'):
        uid=r['id_review']; code=r['codigo_topico']; pair=(uid,code)
        w=float(r['peso'])
        if pair in pairs or uid not in reviews or code not in catalog: raise ValueError('PK/FK de reseña × tópico inválida')
        if not math.isfinite(w) or not 0<=w<=1: raise ValueError('Peso inválido')
        dominant=int(r['es_dominante'])
        if dominant not in (0,1): raise ValueError('Bandera dominante inválida')
        if dominant and reviews[uid]!=code: raise ValueError('Tópico dominante no coincide')
        pairs.add(pair); sums[uid]+=w; dominants[uid]+=dominant
    if any(abs(w-1)>1e-6 or dominants[uid]!=1 for uid,w in sums.items()):
        raise ValueError('Pesos/dominante de tópicos no reconciliados')
    if any(bool(code)!=(uid in sums) for uid,code in reviews.items()): raise ValueError('Puente temático incompleto')
    stats=dict(estado='VALIDADO',resenas=len(reviews),lugares=len(places),con_texto=with_text,
               sin_texto=len(reviews)-with_text,nlp_por_resena=dict(statuses),topicos=len(catalog),
               asociaciones=len(pairs),resenas_con_topicos=len(sums),csv_utf8_bom=True)
    report['validacion_independiente']=stats
    atomic_json(folder/'validacion_final.json',report)
    return stats

if __name__=='__main__':
    import argparse
    from pathlib import Path
    ap=argparse.ArgumentParser(); ap.add_argument('folder',type=Path); ap.add_argument('--allow-pending',action='store_true')
    args=ap.parse_args(); print(json.dumps(validate(args.folder,args.allow_pending),ensure_ascii=False,indent=2))
