"""Comprueba cambios de ficha peruana y conservación de las estrellas."""
from pathlib import Path
import importlib.util
import json
import math
spec=importlib.util.spec_from_file_location('ampliacion',Path(__file__).with_name('pipeline.py'))
p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
old=p.ro(p.OLD/'checkpoint.sqlite'); new=p.ro(p.WORK/'checkpoint.sqlite')
places_old={r['place_key']:json.loads(r['raw_json']) for r in old.execute('SELECT place_key,raw_json FROM places')}
places_new={r['place_key']:json.loads(r['raw_json']) for r in new.execute('SELECT place_key,raw_json FROM places')}
distances=[]; ratings_changed=0
for r in old.execute("SELECT review_id,place_key,raw_json FROM reviews WHERE country='PE'"):
    current=new.execute('SELECT place_key,raw_json FROM reviews WHERE review_id=?',(r['review_id'],)).fetchone()
    if not current: raise ValueError('ID peruano anterior ausente')
    before=json.loads(r['raw_json']); after=json.loads(current['raw_json'])
    ratings_changed+=float(before['rating'])!=float(after['rating'])
    if r['place_key']!=current['place_key']:
        a=places_old[r['place_key']]; b=places_new[current['place_key']]
        lat1,lat2=math.radians(float(a['lat'])),math.radians(float(b['lat']))
        dl=math.radians(float(a['lon'])-float(b['lon']))
        d=2*6371*math.asin(min(1,math.sqrt(math.sin((lat1-lat2)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dl/2)**2)))
        distances.append(d)
report=dict(changed_place_links=len(distances),max_distance_km=max(distances,default=0),
            links_over_1km=sum(d>1 for d in distances),ratings_changed=ratings_changed,
            note='Cercanía geográfica apoya equivalencia física, pero no prueba equivalencia administrativa de fichas.')
p.atomic_json(p.WORK/'auditoria_vinculos_peru.json',report)
print(json.dumps(report),flush=True)
assert not report['links_over_1km'] and not ratings_changed
