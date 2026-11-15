"""Referencias reales etiquetadas por lectura del texto, no por el rating.

Piloto preliminar, no benchmark representativo ni validacion humana independiente.
Las reseñas mixtas/ambiguas se excluyen explícitamente de esta referencia inicial.
Los identificadores vinculan cada etiqueta a una reseña real, sin copiar autores.
"""
import json
from common import DATA_ROOT,atomic_json,connect

LABELS = {
 'ChRDSUhNMG9nS0VJQ0FnSUMwdklrSBAB':'NEGATIVO',
 'ChRDSUhNMG9nS0VJQ0FnSURoaF9GbxAB':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUM1MU0ySU5nEAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUM5MGFtZFZBEAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUM5cnVXcWFnEAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUMtdVBxTUVnEAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUMteXVLMmNBEAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUMwNXVxbE93EAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUMwOGVEMGR3EAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUMxNXN6UUZREAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUN1cGMyb1N3EAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUN1eUtXWUxREAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUN3MEw2a2JBEAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUN3ejhIdFVBEAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUN4MWNMZVpnEAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUN4ajVyRkN3EAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUN5enQzU1d3EAE':'NEUTRO',
 'ChZDSUhNMG9nS0VJQ0FnSUNBcnNPWktnEAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNCZ3N2aUN3EAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNEbExYR1R3EAE':'NEUTRO',
 'ChZDSUhNMG9nS0VJQ0FnSUNHMXVxVk9nEAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNHN3VDN0pREAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNHaHRmb2R3EAE':'NEUTRO',
 'ChZDSUhNMG9nS0VJQ0FnSUNHeUpfZFFREAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNJNjl5SEVnEAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNKOFlHLUZnEAE':'NEUTRO',
 'ChZDSUhNMG9nS0VJQ0FnSUNKdDdDNkZ3EAE':'NEUTRO',
 'ChZDSUhNMG9nS0VJQ0FnSUNNcTlidlRnEAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNOaE1IT1hREAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNRb3Ztb1l3EAE':'NEUTRO',
 'ChZDSUhNMG9nS0VJQ0FnSUNRcXJidExBEAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNSajVlWFZREAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNScU1HZUlREAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNSdUsyVWRREAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNUZ2NTUWZ3EAE':'NEUTRO',
 'ChZDSUhNMG9nS0VJQ0FnSUNVMHJuS0ZBEAE':'NEUTRO',
 'ChZDSUhNMG9nS0VJQ0FnSUNXaDhuUVdBEAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNaNzRXLURnEAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNfNjhiYkZBEAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNlaHBycllnEAE':'NEUTRO',
 'ChZDSUhNMG9nS0VJQ0FnSUNvMTdYWkN3EAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUNxOE1YcGVBEAE':'NEUTRO',
 'ChZDSUhNMG9nS0VJQ0FnSUQ0MFBxUGVREAE':'NEGATIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUQtaGRXX0tnEAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUQteGRMQWZREAE':'POSITIVO',
 'ChZDSUhNMG9nS0VJQ0FnSUQxaHFpQlFBEAE':'POSITIVO',
}

def main():
    path=DATA_ROOT/'piloto/checkpoint.sqlite'
    if not path.exists(): raise FileNotFoundError('Primero ejecutar fase1 --modo piloto')
    cx=connect(path)
    result=[]
    for uid,label in LABELS.items():
        found=cx.execute('SELECT raw_json,country FROM reviews WHERE review_id=?',(uid,)).fetchone()
        if not found: raise ValueError('Referencia no encontrada: '+uid)
        row=json.loads(found['raw_json'])
        result.append(dict(id_review=uid,texto=row['caption'],etiqueta=label,pais=found['country'],
                           metodo_etiquetado='LECTURA_TEXTO_AGENTE_IA_PRELIMINAR'))
    cx.close()
    atomic_json(DATA_ROOT/'evaluacion_referencias.json',result)
    print(f'{len(result)} referencias reales listas. Revisión independiente pendiente.')

if __name__=='__main__': main()
