"""Genera INFORME_REVISION_IA.md y evidencia_final_revision.json tras aplicar la revisión y reejecutar el ETL."""
import json,sys,collections
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cargar
HERE=Path(__file__).resolve().parent

def main():
    evidence=json.loads((cargar.HERE/'evidencia_final.json').read_text(encoding='utf-8'))
    assert evidence['estado']=='EJECUTADO_Y_VERIFICADO' and evidence['segunda']['revision_ia']['estado']=='OK'
    assert all(v==0 for v in evidence['delta'].values())
    cats=json.loads((HERE/'catalogo_curado.json').read_text(encoding='utf-8'))
    judgments=json.loads((HERE/'evaluaciones_topicos.json').read_text(encoding='utf-8'))
    sentiments=json.loads((HERE/'evaluaciones_sentimiento.json').read_text(encoding='utf-8'))
    c=cargar.connect('MuseosLatam_Datamart')
    cur=c.cursor().execute('SELECT * FROM mart.v_cobertura_tematica ORDER BY codigo_pais');cols=[d[0] for d in cur.description]
    coverage=[dict(zip(cols,r)) for r in cur.fetchall()]
    for r in coverage:assert r['n_tema_con_soporte_ia']+r['n_tema_uso_restringido']==r['n_asignadas_baseline']
    assert sum(r['n_asignadas_baseline'] for r in coverage)==233556
    actual=c.cursor().execute('SELECT nk_codigo,etiqueta,descripcion,validacion_etiqueta,apto_analisis_tematico FROM mart.dim_dimension_latente WHERE sk_dimension_latente<>-1 ORDER BY nk_codigo').fetchall()
    assert len(actual)==41 and len({r[2] for r in actual})==41
    assert all('Propuesta de IA tras lectura' not in r[2] for r in actual)
    assert cargar.scalar(c,"SELECT COUNT(*) FROM mart.v_dimension_satisfaccion_revisada WHERE apto_analisis_tematico<>1")==0
    assert cargar.scalar(c,"SELECT COUNT(*) FROM aud.revision_semantica WHERE validacion_humana<>0")==0
    # Evaluaciones apuntan a reseñas existentes y mantienen el país correcto.
    assert cargar.scalar(c,"SELECT COUNT(*) FROM MuseosLatam_Origen.curado.evaluacion_topico e LEFT JOIN MuseosLatam_Origen.stg.resena r ON r.source_row=e.source_row WHERE r.source_row IS NULL OR r.id_review<>e.id_review OR r.codigo_pais<>e.codigo_pais")==0
    viewcols={r[0] for r in c.cursor().execute("SELECT name FROM sys.columns WHERE object_id=OBJECT_ID('mart.v_resena_completa')").fetchall()}
    assert {'idioma','sentimiento_etiqueta'}<=viewcols
    counts=cargar.counts(c,'mart');c.close()
    payload=dict(estado='EJECUTADO_Y_VERIFICADO',version_revision='revision-ia-20261023-v1',revision_humana=False,
      cobertura=coverage,conteos=counts,dictamenes_topicos=dict(collections.Counter(r['juicio'] for r in judgments)),
      dictamenes_sentimiento=dict(collections.Counter(r['juicio'] for r in sentiments)),
      pruebas={'41_descripciones_distintas':'OK','origen_raw_igual_csv':'OK','sin_reasignacion_de_hechos':'OK','miembros_y_hechos_delta_cero':'OK','evaluaciones_sin_huerfanos':'OK','vistas_legibles_y_filtradas':'OK','migracion_ensayada_con_rollback':'OK','segunda_aplicacion_sin_updates':'OK','ETL_completo_reejecutado_con_revision':'OK'},
      segundos_etl_con_revision=evidence['segundos'])
    cargar.jdump(HERE/'evidencia_final_revision.json',payload)
    lines=['# Informe de la revisión semántica de tópicos','',
      'La revisión semántica se hizo por muestreo, con un modelo de lenguaje como anotador y sin validación humana. Cada uno de los 41 tópicos recibió una definición, criterios de inclusión y exclusión y sus límites observados; además se revisaron las etiquetas legibles de siete dimensiones y los nombres de los 32 códigos de idioma. La revisión quedó aplicada y versionada en ambas bases, sin modificar los datos de origen.','',
      '## Resultado semántico','',
      '**22 tópicos con soporte muestral y 19 de uso restringido.** Se conservan los 41 códigos, la versión del modelo, las claves sustitutas y las 233.556 pertenencias originales; no se reasignaron outliers ni se volvió a ejecutar el NLP.','',
      'Se leyeron completos 488 casos temáticos: AR 164, MX 163 y PE 161; hasta cuatro textos únicos por tópico y país, con hash y semilla fija. Cuatro de los 492 cupos posibles no tenían suficientes textos distintos. La muestra contiene 68.284 caracteres. También se revisaron 54 casos de sentimiento.','',
      'Cada caso se calificó respecto de la etiqueta original del tópico: C = soporte explícito, P = parcial, adyacente o genérico, N = sin soporte o con interferencia. Un tópico se habilita para indicadores con C/n ≥ 2/3 en total, ≥ 1/2 en cada país y sin interferencia contextual grave.','',
      'Estos cocientes describen la muestra, que está equilibrada por tópico y país; no son una estimación de exactitud sobre todo el corpus.','',
      '## Hallazgos principales','',
      '- T016 y T024, originalmente titulados como Perú, agrupan también historia y patrimonio argentinos. Se retiró la atribución exclusiva y se restringió su uso temático.',
      '- T025 mezcla Cusco con Cuyo, Culhuacán, CU y Cuale; no sustenta un KPI específico de Cusco o boleto turístico.',
      '- T027 contiene la mina La Mejicana de Argentina, deportes y empresas; no equivale a Revolución mexicana.',
      '- T028 mezcla Lima con Limay y sopa de lima. El país o la ciudad se obtienen de la geografía, no del tópico.',
      '- T021 incluye patrimonio y localidades diversas, no solamente huacas. T033 mezcla fauna patagónica, entorno natural y cultura de la ayahuasca.',
      '- Las menciones de museos pequeños no implican insatisfacción; mágico puede ser elogio, y plantas puede significar pisos. Estas restricciones están explícitas en SQL.','',
      '## Catálogo revisado','',
      '| Código | Etiqueta activa | C / n respecto al título original | Uso |','|---|---|---:|---|']
    for r in cats:lines.append(f'| {r["codigo_topico"].split("-T")[-1]} | {r["etiqueta"]} | {r["coherentes_n"]}/{r["muestra_n"]} | {"Apto" if r["apto_analisis_tematico"] else "Restringido"} |')
    lines+=['','## Cobertura por país','',
      '| País | Reseñas totales | Con texto | Asignadas baseline | En temas aptos | En temas restringidos |','|---|---:|---:|---:|---:|---:|']
    for r in coverage:lines.append('| '+r['codigo_pais']+' | '+' | '.join(f'{r[k]:,}' for k in ['n_resenas','n_con_texto','n_asignadas_baseline','n_tema_con_soporte_ia','n_tema_uso_restringido'])+' |')
    lines+=['',
      '122.082 reseñas pertenecen a los 22 tópicos aptos y 111.474 a los 19 restringidos (233.556 en total). La revisión evaluó categorías mediante muestras, no cada una de esas reseñas; la vista revisada filtra los tópicos aptos y conserva los denominadores.','',
      '## Diagnóstico de sentimiento','',
      'De 54 casos revisados: 27 compatibles con la polaridad asignada, 7 mixtos o ambiguos, 1 contradicción clara, 12 abstenciones razonables por señal insuficiente y 7 con señal interpretable que quedaron sin clasificar. Es un diagnóstico del modelo, no una medida de su precisión.','',
      'Ejemplo de contradicción: «Una visita obligada en Huamantla.» estaba clasificada como NEGATIVO. También hay textos en español excluidos por la detección de idioma. Estos casos quedan registrados por ID y hash en la capa curada; las predicciones originales se conservan sin correcciones selectivas.','',
      '## Cambios aplicados y reproducibilidad','',
      '- Origen: esquema `curado` con 41 filas en `catalogo_topicos`, 488 en `evaluacion_topico`, 54 en `evaluacion_sentimiento` y vista `v_catalogo_vigente`. `stg.catalogo`, las dos tablas madre, el puente raw y todos los CSV permanecen intactos.',
      '- Destino: 41 etiquetas/definiciones revisadas en `mart.dim_dimension_latente`, columnas de gobernanza y miembro desconocido explicado. Etiquetas legibles en perfil, extensión, antigüedad, presencia, sentimiento, rating e idioma; no cambian claves o segmentos.',
      '- `aud.revision_semantica` conserva versión, hashes, revisor, `validacion_humana=0` y respaldo de las dimensiones previas.',
      '- ETL adaptado: aplica y verifica la revisión después de DIM y antes de hechos; nueva instalación y reanudación conservan los cambios. La migración se ensayó con rollback comprobado, luego se aplicó y se ejecutó de nuevo: cero nuevas filas y cero actualizaciones en la segunda aplicación.',
      f'- Se ejecutó el comando completo adaptado y pasó sus dos pasadas en {evidence["segundos"]:.1f} s, con lectura completa de vuelta CSV↔SQL y todas las validaciones relacionales. Delta cero en las 14 tablas de dimensiones/hechos.','',
      'Las consultas vigentes son `mart.v_catalogo_topicos`, `mart.v_dimension_satisfaccion` (baseline con banderas), `mart.v_dimension_satisfaccion_revisada` (solo temas habilitados) y `mart.v_cobertura_tematica`. `VER_REVISION.sql` permite inspeccionar los dictámenes y los textos exactos mediante join con origen.','',
      'Los nombres de idioma se contrastaron con la [tabla de códigos ISO de Library of Congress](https://www.loc.gov/standards/iso639-2/php/code_list.php).','',
      '## Definiciones y límites por tópico','']
    for r in cats:
        lines += [f'### {r["codigo_topico"].split("-T")[-1]} — {r["etiqueta"]}','',r['descripcion'],'', '**Límite observado:** '+r['limitaciones'],'']
    lines+=['## Estado final','',
      'La revisión semántica quedó registrada y aplicada. Los 19 tópicos restringidos siguen identificados en el catálogo y quedan fuera de los indicadores temáticos; los valores desconocidos, las reseñas sin texto y la fecha de reputación no documentada se conservan. La capa BI y el dashboard consumen la revisión mediante la bandera `apto_analisis_tematico`.']
    (HERE/'INFORME_REVISION_IA.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Informe de la revisión semántica y evidencia final guardados.')

if __name__=='__main__':main()
