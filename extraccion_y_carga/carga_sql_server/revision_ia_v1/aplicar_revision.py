"""Migración versionada de la revisión semántica. No actualiza stg ni hechos.
Uso: python aplicar_revision.py --ensayo (ROLLBACK) / sin opciones (COMMIT).
"""
import sys,json,hashlib,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cargar
from revision_ia_v1.contenido import REVISION,MODELO,ETIQUETAS,IDIOMAS
HERE=Path(__file__).resolve().parent

def artifacts():
    meta=json.loads((HERE/'manifiesto_revision.json').read_text(encoding='utf-8'))
    for f,h in meta['archivos'].items():
        assert hashlib.sha256((HERE/f).read_bytes()).hexdigest()==h,('Artefacto de revisión alterado',f)
    return (json.loads((HERE/'catalogo_curado.json').read_text(encoding='utf-8')),
      json.loads((HERE/'evaluaciones_topicos.json').read_text(encoding='utf-8')),
      json.loads((HERE/'evaluaciones_sentimiento.json').read_text(encoding='utf-8')),
      hashlib.sha256((HERE/'manifiesto_revision.json').read_bytes()).hexdigest())

def snapshot(c):
    out={}
    for name in ['dimension_latente',*ETIQUETAS]:
        cur=c.cursor().execute(f'SELECT * FROM mart.dim_{name} ORDER BY sk_{name}')
        cols=[d[0] for d in cur.description];out[name]=[dict(zip(cols,list(r))) for r in cur.fetchall()]
    return out

def views(c,origin):
    destination=cargar.scalar(c,'SELECT DB_NAME()')
    assert destination in ['MuseosLatam_Datamart','MuseosLatam_Datamart_Piloto']
    sql=(HERE/'05_vistas_revision.sql').read_text(encoding='utf-8').replace('{{ORIGEN}}',origin).replace('{{DESTINO}}',destination)
    cargar.execute_script(c,sql)

def apply(c,origin='MuseosLatam_Origen'):
    assert origin in ['MuseosLatam_Origen','MuseosLatam_Origen_Piloto']
    catalog,topics,sentiment,evidence_hash=artifacts()
    # El piloto de ingestión no contiene las 542 muestras de revisión; conserva la versión raw.
    if origin.endswith('_Piloto'):return {'estado':'NO_APLICA_PILOTO_DE_INGESTION'}
    previous=snapshot(c)
    ddl=(HERE/'04_revision.sql').read_text(encoding='utf-8').replace('{{ORIGEN}}',origin)
    cargar.execute_script(c,ddl)
    applied=c.cursor().execute('SELECT evidencia_sha256 FROM aud.revision_semantica WHERE version_revision=?',REVISION).fetchone()
    if applied:
        if applied[0]!=evidence_hash:raise ValueError('Revisión ya aplicada con otro contenido: requiere versión nueva')
        views(c,origin)
        return {'estado':'YA_APLICADA','version':REVISION,'filas_actualizadas':0}
    source=c.cursor().execute(f'SELECT codigo_topico,version_modelo FROM [{origin}].stg.catalogo').fetchall()
    assert set(map(tuple,source))=={(r['codigo_topico'],r['version_modelo']) for r in catalog}
    # Comprobar que todas las anotaciones se refieren a textos existentes y exactos.
    ids=sorted({r['id_review'] for r in topics+sentiment})
    placeholders=','.join('?' for _ in ids)
    observed={r[0]:(r[1],hashlib.sha256(r[2].encode('utf-8')).hexdigest()) for r in c.cursor().execute(f'SELECT id_review,source_row,caption FROM [{origin}].stg.resena WHERE id_review IN ({placeholders})',*ids).fetchall()}
    assert len(observed)==len(ids)
    for r in topics+sentiment:assert observed[r['id_review']][1]==r['sha256_texto']
    fields=['version_revision','codigo_topico','version_modelo','etiqueta','descripcion','criterios_inclusion','criterios_exclusion','limitaciones','palabras_clave','validacion_etiqueta','apto_analisis_tematico','muestra_n','coherentes_n','parciales_n','no_coherentes_n','soporte_muestral','metodo_revision','detalle_paises','etiqueta_anterior','evidencia_sha256']
    for r in catalog:
        values=[json.dumps(r[k],ensure_ascii=False) if k=='detalle_paises' else evidence_hash if k=='evidencia_sha256' else r[k] for k in fields]
        c.execute(f'INSERT [{origin}].curado.catalogo_topicos('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',*values)
    for r in topics:
        c.execute(f'INSERT [{origin}].curado.evaluacion_topico VALUES(?,?,?,?,?,?,?,?,?)',REVISION,r['codigo_topico'],r['codigo_pais'],r['numero'],r['id_review'],observed[r['id_review']][0],r['sha256_texto'],r['juicio'],r['criterio'])
    for r in sentiment:
        c.execute(f'INSERT [{origin}].curado.evaluacion_sentimiento VALUES(?,?,?,?,?,?,?,?,?,?)',REVISION,r['numero'],r['id_review'],observed[r['id_review']][0],r['codigo_pais'],r['sentimiento_original'],r['estado_original'],r['sha256_texto'],r['juicio'],r['dictamen'])
    update=f"""UPDATE d SET etiqueta=s.etiqueta,descripcion=s.descripcion,palabras_clave=s.palabras_clave,validacion_etiqueta=s.validacion_etiqueta,
version_revision=s.version_revision,criterios_inclusion=s.criterios_inclusion,criterios_exclusion=s.criterios_exclusion,limitaciones=s.limitaciones,
apto_analisis_tematico=s.apto_analisis_tematico,muestra_revisada=s.muestra_n,soporte_muestral=s.soporte_muestral,metodo_revision=s.metodo_revision
FROM mart.dim_dimension_latente d JOIN [{origin}].curado.catalogo_topicos s ON s.codigo_topico=d.nk_codigo AND s.version_modelo=d.version_modelo WHERE s.version_revision=?"""
    c.execute(update,REVISION)
    c.execute("UPDATE mart.dim_dimension_latente SET descripcion=N'Reseña sin tópico asignado en el baseline; conserva su existencia en el hecho de reseñas.',version_revision=?,criterios_inclusion=N'No aplica: miembro desconocido.',criterios_exclusion=N'No representa un tópico adicional.',limitaciones=N'No se crean pertenencias para reseñas sin asignación.',apto_analisis_tematico=0,muestra_revisada=0,soporte_muestral=NULL,metodo_revision=N'Miembro técnico; no requiere evaluación semántica.',validacion_etiqueta='NO_APLICA' WHERE sk_dimension_latente=-1",REVISION)
    for dim,mapping in ETIQUETAS.items():
        existing={r[0] for r in c.cursor().execute(f'SELECT nk_codigo FROM mart.dim_{dim}').fetchall()}
        assert existing==set(mapping),(dim,existing-set(mapping),set(mapping)-existing)
        for code,label in mapping.items():
            if dim=='idioma':c.execute('UPDATE mart.dim_idioma SET etiqueta=?,nombre=? WHERE nk_codigo=?',label,label,code)
            else:c.execute(f'UPDATE mart.dim_{dim} SET etiqueta=? WHERE nk_codigo=?',label,code)
    c.execute('INSERT aud.revision_semantica(version_revision,evidencia_sha256,revisor,validacion_humana,respaldo) VALUES(?,?,?,?,?)',REVISION,evidence_hash,'Agente IA Codex',False,json.dumps(previous,ensure_ascii=False))
    views(c,origin)
    return {'estado':'APLICADA','version':REVISION,'topicos':41,'evaluaciones_topicos':488,'evaluaciones_sentimiento':54,'uso_habilitado':22,'uso_restringido':19}

def validate(c,origin='MuseosLatam_Origen'):
    catalog,topics,sentiment,h=artifacts()
    assert cargar.scalar(c,'SELECT COUNT(*) FROM aud.revision_semantica WHERE version_revision=? AND evidencia_sha256=? AND validacion_humana=0',REVISION,h)==1
    assert cargar.scalar(c,f'SELECT COUNT(*) FROM [{origin}].curado.catalogo_topicos WHERE version_revision=?',REVISION)==41
    assert cargar.scalar(c,f'SELECT COUNT(*) FROM [{origin}].curado.evaluacion_topico WHERE version_revision=?',REVISION)==488
    assert cargar.scalar(c,f'SELECT COUNT(*) FROM [{origin}].curado.evaluacion_sentimiento WHERE version_revision=?',REVISION)==54
    checks=['etiqueta','descripcion','palabras_clave','validacion_etiqueta','version_revision','criterios_inclusion','criterios_exclusion','limitaciones','apto_analisis_tematico','muestra_revisada','soporte_muestral','metodo_revision']
    expr_s=['s.'+{'muestra_revisada':'muestra_n'}.get(k,k) for k in checks]
    compare='SELECT '+','.join('d.'+k for k in checks)+' EXCEPT SELECT '+','.join(expr_s)
    assert cargar.scalar(c,f'SELECT COUNT(*) FROM mart.dim_dimension_latente d JOIN [{origin}].curado.catalogo_topicos s ON s.codigo_topico=d.nk_codigo AND s.version_modelo=d.version_modelo WHERE s.version_revision=? AND EXISTS({compare})',REVISION)==0
    assert cargar.scalar(c,"SELECT COUNT(*) FROM mart.dim_dimension_latente WHERE sk_dimension_latente<>-1 AND (descripcion LIKE N'Propuesta de IA%' OR validacion_etiqueta='PROPUESTA_IA_REVISAR_EQUIPO')")==0
    for dim,labels in ETIQUETAS.items():
        actual={r[0]:r[1] for r in c.cursor().execute(f'SELECT nk_codigo,etiqueta FROM mart.dim_{dim}').fetchall()};assert actual==labels,dim
    assert cargar.scalar(c,'SELECT COUNT(*) FROM mart.dim_idioma WHERE nombre<>etiqueta')==0
    # El catálogo raw sigue idéntico al CSV, incluidos sus avisos históricos de propuesta.
    with (cargar.FINAL/'catalogo_dimensiones_latentes.csv').open(encoding='utf-8-sig',newline='') as stream:
        import csv
        reader=csv.DictReader(stream);headers=reader.fieldnames
        expected=[tuple(r[k] for k in headers) for r in reader]
    actual=[tuple(r) for r in c.cursor().execute('SELECT '+','.join('['+k+']' for k in headers)+f' FROM [{origin}].stg.catalogo ORDER BY source_row').fetchall()]
    assert actual==expected
    return {'estado':'OK','catalogo_versionado':41,'muestras_topicos':488,'muestras_sentimiento':54,'etiquetas_y_32_idiomas':'OK','origen_raw_preservado':True,'sin_validacion_humana_simulada':True}

def main():
    p=argparse.ArgumentParser();p.add_argument('--ensayo',action='store_true');a=p.parse_args()
    master=cargar.connect(autocommit=True)
    lock=cargar.scalar(master,"DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource='MuseosLatamSQL-carga',@LockMode='Exclusive',@LockOwner='Session',@LockTimeout=0; SELECT @r")
    if lock<0:raise RuntimeError('Hay otro proceso de carga o revisión activo')
    c=cargar.connect('MuseosLatam_Datamart')
    try:
        before=cargar.counts(c,'mart');result=apply(c);check=validate(c)
        if a.ensayo:c.rollback()
        else:c.commit()
        after=cargar.counts(c,'mart');assert before==after
        payload={'ensayo_rollback':a.ensayo,'resultado':result,'validacion':check,'antes':before,'despues':after,'delta':{k:after[k]-v for k,v in before.items()}}
        cargar.jdump(HERE/('evidencia_ensayo.json' if a.ensayo else 'evidencia_aplicacion.json'),payload)
        print(json.dumps(payload,ensure_ascii=False))
    except BaseException:c.rollback();raise
    finally:c.close();master.close()

if __name__=='__main__':main()
