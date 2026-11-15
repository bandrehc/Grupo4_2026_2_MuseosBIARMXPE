-- Solo lectura. El catálogo activo es curado; stg conserva el catálogo original.
USE MuseosLatam_Datamart;
SELECT validacion_etiqueta,apto_analisis_tematico,COUNT(*) topicos,SUM(muestra_revisada) textos_revisados
FROM mart.dim_dimension_latente WHERE sk_dimension_latente<>-1 GROUP BY validacion_etiqueta,apto_analisis_tematico;
SELECT * FROM mart.v_catalogo_topicos ORDER BY codigo_topico;
SELECT * FROM mart.v_cobertura_tematica ORDER BY codigo_pais;
SELECT * FROM mart.v_dimension_satisfaccion_revisada ORDER BY codigo_pais,n_asignadas DESC;
SELECT version_revision,evidencia_sha256,aplicado_utc,revisor,validacion_humana FROM aud.revision_semantica;
USE MuseosLatam_Origen;
SELECT * FROM curado.v_catalogo_vigente ORDER BY codigo_topico;
SELECT codigo_topico,codigo_pais,juicio,COUNT(*) n FROM curado.evaluacion_topico GROUP BY codigo_topico,codigo_pais,juicio ORDER BY codigo_topico,codigo_pais,juicio;
SELECT e.codigo_topico,e.codigo_pais,e.numero,e.juicio,e.criterio,r.caption
FROM curado.evaluacion_topico e JOIN stg.resena r ON r.source_row=e.source_row
ORDER BY e.codigo_topico,e.codigo_pais,e.numero;
SELECT e.numero,e.codigo_pais,e.sentimiento_original,e.estado_original,e.juicio,e.dictamen,r.caption
FROM curado.evaluacion_sentimiento e JOIN stg.resena r ON r.source_row=e.source_row ORDER BY e.numero;
