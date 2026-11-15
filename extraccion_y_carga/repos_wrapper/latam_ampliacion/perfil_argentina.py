"""Perfil adicional de incidencias y señales textuales, sin exponer autores."""
from pathlib import Path
import importlib.util
import json
from collections import Counter
spec=importlib.util.spec_from_file_location('ampliacion',Path(__file__).with_name('pipeline.py'))
p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
cx=p.ro(p.WORK/'checkpoint.sqlite')
stats=Counter(); examples=[]
for i,r in enumerate(cx.execute("SELECT r.raw_json,q.flags FROM reviews r JOIN review_quality q USING(review_id) WHERE r.country='AR' ORDER BY r.review_id")):
    raw=json.loads(r['raw_json']); flags=json.loads(r['flags']); text=raw['caption'].strip()
    stats['rows']+=1
    if text:
        if 'RATING_AUSENTE' in flags: stats['missing_rating_with_text']+=1
        if text.endswith(('…','...')): stats['text_ends_ellipsis']+=1
        low=text.casefold()
        if any(marker in low for marker in ['traducido por google','translated by google']): stats['translation_marker']+=1
        if low in ('más','mas','ver más','more','see more','ver traducción'): stats['only_ui_marker']+=1
    if i%40000==0 and text:
        examples.append(dict(museum=raw['nombre_lugar'],category=raw['categoria_google'],rating=raw['rating'],excerpt=text[:220]))
report=dict(counts=dict(stats),note='Puntos suspensivos son una señal heurística, no prueba de truncamiento. Marcador ausente no demuestra texto sin traducir.')
p.atomic_json(p.WORK/'perfil_calidad_argentina.json',report)
print(json.dumps(report,ensure_ascii=False),flush=True)
print(json.dumps(dict(sample_excerpts=examples),ensure_ascii=False),flush=True)
