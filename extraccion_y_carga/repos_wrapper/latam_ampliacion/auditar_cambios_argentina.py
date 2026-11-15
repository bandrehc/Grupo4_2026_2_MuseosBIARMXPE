"""Comparación campo a campo de Argentina cruda/publicada, sin exponer reseñas."""
import importlib.util
from pathlib import Path
from collections import Counter
import json
spec=importlib.util.spec_from_file_location('ampliacion',Path(__file__).with_name('pipeline.py'))
p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
cx=p.ro(p.WORK/'checkpoint.sqlite')
fields=Counter(); numeric_equivalent=Counter(); changed_rows=0; comparisons=0
for line,raw in p.rows(p.REPO/'data/resenas/paquetes/comentarios_museos_crudo_argentina.csv.gz'):
    current=cx.execute('SELECT raw_json FROM reviews WHERE review_id=?',(raw['id_review'],)).fetchone()
    if current is None: raise ValueError('Reseña argentina ausente')
    published=json.loads(current['raw_json'])
    differences=[key for key in p.REVIEW_FIELDS if raw[key]!=published[key]]
    fields.update(differences); changed_rows+=bool(differences); comparisons+=1
    for key in differences:
        if key=='n_review_user':
            try:
                if p.integer(raw[key])==p.integer(published[key]): numeric_equivalent[key]+=1
            except (ValueError,OverflowError): pass
    if comparisons%100000==0: print('comparadas',comparisons,flush=True)
report=dict(compared=comparisons,changed_rows=changed_rows,changed_fields=dict(fields),numeric_equivalent_changes=dict(numeric_equivalent),
            note='Comparación exacta de strings; no se modificaron fuentes ni se imprimieron textos/autores.')
p.atomic_json(p.WORK/'cambios_argentina_crudo_publicado.json',report)
print(json.dumps(report,ensure_ascii=False),flush=True)
