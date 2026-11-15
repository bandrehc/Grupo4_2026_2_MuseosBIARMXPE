"""Audita columnas comunes frente a una base explícita; NMF por defecto."""
import argparse
import csv
import json
from itertools import zip_longest
from pathlib import Path
from experiment import FINAL,atomic_json,digest,utcnow
ALLOWED={'estado_topicos','topico_dominante','version_modelo_topicos'}

def check(folder,source_folder=None):
    # Permite indicar otra carpeta base sin duplicar el CSV NMF de 872 MB.
    # Se comparan las mismas columnas comunes; las tres temáticas siguen excluidas.
    baseline=Path(source_folder) if source_folder is not None else FINAL
    source=baseline/'base_madre_resenas.csv'; dest=folder/'base_madre_resenas.csv'; total=0
    with source.open(encoding='utf-8-sig',newline='') as a,dest.open(encoding='utf-8-sig',newline='') as b:
        reader_a=csv.DictReader(a); reader_b=csv.DictReader(b)
        if reader_a.fieldnames!=reader_b.fieldnames: raise ValueError('Cambió el esquema de columnas')
        compare=[c for c in reader_a.fieldnames if c not in ALLOWED]
        for left,right in zip_longest(reader_a,reader_b):
            total+=1
            if left is None or right is None: raise ValueError('Se perdieron/multiplicaron reseñas')
            if any(left[c]!=right[c] for c in compare): raise ValueError('Cambió información común/original en '+str(left.get('id_review')))
    if digest(baseline/'base_madre_lugares.csv')!=digest(folder/'base_madre_lugares.csv'): raise ValueError('Cambió tabla de lugares')
    report=dict(estado='VALIDADO',fecha=utcnow(),filas=total,columnas_iguales=compare,columnas_permitidas=sorted(ALLOWED),source_sha256=digest(source),output_sha256=digest(dest))
    atomic_json(folder/'conservacion_columnas.json',report); print(f'Conservación {folder.name}: {total} reseñas; todas las columnas salvo las tres temáticas idénticas.',flush=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('method',choices=['LDA','S-BERT']); check(FINAL/parser.parse_args().method)
