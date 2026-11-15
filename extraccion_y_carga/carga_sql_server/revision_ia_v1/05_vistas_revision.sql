USE [{{ORIGEN}}];
GO
CREATE OR ALTER VIEW curado.v_catalogo_vigente AS
SELECT * FROM curado.catalogo_topicos WHERE version_revision='revision-ia-20261023-v1';
GO
USE [{{DESTINO}}];
GO
CREATE OR ALTER VIEW mart.v_catalogo_topicos AS
SELECT nk_codigo codigo_topico,version_modelo,etiqueta,descripcion,palabras_clave,version_revision,
 validacion_etiqueta,apto_analisis_tematico,criterios_inclusion,criterios_exclusion,limitaciones,
 muestra_revisada,soporte_muestral,metodo_revision
FROM mart.dim_dimension_latente WHERE sk_dimension_latente<>-1;
GO
CREATE OR ALTER VIEW mart.v_dimension_satisfaccion AS
SELECT f.codigo_pais,d.nk_codigo,d.version_modelo,d.etiqueta,d.version_revision,d.validacion_etiqueta,d.apto_analisis_tematico,
COUNT_BIG(*) n_asignadas,SUM(CASE WHEN f.rating IS NOT NULL THEN w.peso ELSE 0 END) peso_con_rating,
SUM(f.rating*w.peso)/NULLIF(SUM(CASE WHEN f.rating IS NOT NULL THEN w.peso ELSE 0 END),0) rating_ponderado
FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena
JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente
GROUP BY f.codigo_pais,d.nk_codigo,d.version_modelo,d.etiqueta,d.version_revision,d.validacion_etiqueta,d.apto_analisis_tematico;
GO
CREATE OR ALTER VIEW mart.v_dimension_satisfaccion_revisada AS
SELECT * FROM mart.v_dimension_satisfaccion WHERE apto_analisis_tematico=1;
GO
CREATE OR ALTER VIEW mart.v_cobertura_tematica AS
WITH asignacion AS (
 SELECT w.sk_resena,MAX(CONVERT(int,d.apto_analisis_tematico)) habilitada
 FROM mart.fact_resena_dimension w JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente
 GROUP BY w.sk_resena
)
SELECT f.codigo_pais,COUNT_BIG(*) n_resenas,SUM(CONVERT(bigint,f.tiene_texto)) n_con_texto,
SUM(CASE WHEN a.sk_resena IS NOT NULL THEN CONVERT(bigint,1) ELSE 0 END) n_asignadas_baseline,
SUM(CASE WHEN a.habilitada=1 THEN CONVERT(bigint,1) ELSE 0 END) n_tema_con_soporte_ia,
SUM(CASE WHEN a.habilitada=0 THEN CONVERT(bigint,1) ELSE 0 END) n_tema_uso_restringido,
SUM(CASE WHEN a.habilitada=1 THEN 1.0 ELSE 0 END)/NULLIF(SUM(CONVERT(bigint,f.tiene_texto)),0) cobertura_soporte_ia_sobre_texto
FROM mart.fact_resena f LEFT JOIN asignacion a ON a.sk_resena=f.sk_resena GROUP BY f.codigo_pais;
