import csv,json,pathlib,collections,hashlib,time,os
root=pathlib.Path(__file__).resolve().parents[1]; f=root/'data/preparacion_latam/ampliacion_2026-10-22_v1/final'; out={}
for p in f.glob('*.csv'):
 maxlen=collections.Counter(); vals=collections.defaultdict(collections.Counter); n=0; samples={}; stats=collections.defaultdict(collections.Counter); ids=set(); duplicates=0; longest=None
 with p.open(encoding='utf-8-sig',newline='') as s:
  c=csv.DictReader(s); headers=c.fieldnames
  for row in c:
   n+=1
   for k,v in row.items():
    maxlen[k]=max(maxlen[k],len(v.encode('utf-16-le'))//2)
    if k.startswith('segmento_') or k in ['precision_fecha_resena','periodo_codigo','sentimiento','estado_nlp','codigo_idioma','precision_observacion_reputacion']:vals[k][v]+=1
   if p.name=='base_madre_resenas.csv':
    key=row['id_review'];duplicates+=key in ids;ids.add(key)
    country=row['codigo_pais'];st=stats[country];st['rows']+=1;st['null_rating']+=not row['rating'];st['with_text']+=int(row['tiene_texto']);st['sum_rating']+=int(float(row['rating'])) if row['rating'] else 0;st['sum_words']+=int(row['cantidad_palabras'])
    flags=[country,'text' if row['caption'] else 'no_text','null_rating' if not row['rating'] else '',row['precision_fecha_resena'],'ambiguous' if 'HISTORIAL_AUTOR_INVALIDO' in row['banderas_calidad'] else '', 'unicode' if '\ufffd' in row['caption'] else '', 'newline' if '\n' in row['caption'] else '', 'quote' if '"' in row['caption'] else '', 'comma' if ',' in row['caption'] else '', 'topic' if row['topico_dominante'] else 'no_topic']
    for flag in filter(None,flags):samples.setdefault(flag,row)
    if longest is None or len(row['caption'])>len(longest['caption']):longest=row
   elif p.name=='base_madre_lugares.csv':
    st=stats[row['codigo_pais']];st['rows']+=1
    for k in ['stars','reviews']:
     if row[k]:st['non_null_'+k]+=1;st['sum_'+k]+=float(row[k])
    st['reputation_rows']+=bool(row['stars'] or row['reviews'])
 if longest:samples['longest']=longest
 out[p.name]={'rows':n,'headers':headers,'max_utf16':dict(maxlen),'values':dict(vals),'stats':dict(stats),'duplicates':duplicates}
 if samples:(pathlib.Path(os.environ['LOCALAPPDATA'])/'MuseosLatamSQL/pilot_samples.json').write_text(json.dumps(list({r['id_review']:r for r in samples.values()}.values()),ensure_ascii=False,indent=2),encoding='utf-8')
 print(p.name,n,dict(stats),flush=True)
(root/'carga_sql_server/perfil_fuentes.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
