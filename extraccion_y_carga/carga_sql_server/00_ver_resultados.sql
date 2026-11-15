-- Conectar a la instancia SQL Server local. Solo lectura.
SELECT @@SERVERNAME instancia,@@VERSION motor;
SELECT name,collation_name,recovery_model_desc FROM sys.databases WHERE name LIKE 'MuseosLatam_%';
GO
USE [MuseosLatam_Origen];
SELECT 'resena' tabla,COUNT_BIG(*) filas FROM stg.resena
UNION ALL SELECT 'lugar',COUNT_BIG(*) FROM stg.lugar
UNION ALL SELECT 'catalogo',COUNT_BIG(*) FROM stg.catalogo
UNION ALL SELECT 'puente',COUNT_BIG(*) FROM stg.puente;
SELECT * FROM aud.fuente;
SELECT fase,tabla,COUNT_BIG(*) lotes,MAX(fin) ultimo_checkpoint,MAX(confirmado) ultima_confirmacion FROM aud.lote GROUP BY fase,tabla;
SELECT regla,COUNT_BIG(*) incidencias FROM aud.incidencia GROUP BY regla;
GO
USE [MuseosLatam_Datamart];
SELECT 'fact_resena' tabla,COUNT_BIG(*) filas FROM mart.fact_resena
UNION ALL SELECT 'fact_resena_dimension',COUNT_BIG(*) FROM mart.fact_resena_dimension
UNION ALL SELECT 'fact_reputacion_lugar',COUNT_BIG(*) FROM mart.fact_reputacion_lugar;
SELECT codigo_pais,COUNT_BIG(*) resenas,COUNT(DISTINCT nk_id_review) ids_unicos,COUNT_BIG(*)-COUNT_BIG(rating) ratings_null,
SUM(CONVERT(bigint,rating)) suma_rating,1.0*SUM(CONVERT(bigint,rating))/NULLIF(COUNT_BIG(rating),0) rating_promedio,
SUM(CONVERT(bigint,tiene_texto)) con_texto FROM mart.fact_resena GROUP BY codigo_pais;
SELECT nk_id_review,COUNT_BIG(*) n FROM mart.fact_resena GROUP BY nk_id_review HAVING COUNT_BIG(*)>1;
SELECT sk_resena,sk_dimension_latente,COUNT_BIG(*) n FROM mart.fact_resena_dimension GROUP BY sk_resena,sk_dimension_latente HAVING COUNT_BIG(*)>1;
SELECT COUNT_BIG(*) reseñas_faltantes FROM MuseosLatam_Origen.stg.resena s WHERE NOT EXISTS(SELECT 1 FROM mart.fact_resena f WHERE f.nk_id_review=s.id_review);
SELECT COUNT_BIG(*) reseñas_sobrantes FROM mart.fact_resena f WHERE NOT EXISTS(SELECT 1 FROM MuseosLatam_Origen.stg.resena s WHERE f.nk_id_review=s.id_review);
SELECT COUNT_BIG(*) huerfanas FROM mart.fact_resena f LEFT JOIN mart.dim_lugar l ON l.sk_lugar=f.sk_lugar WHERE l.sk_lugar IS NULL;
SELECT COUNT_BIG(*) puente_huerfano FROM mart.fact_resena_dimension w LEFT JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena LEFT JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente WHERE f.sk_resena IS NULL OR d.sk_dimension_latente IS NULL;
SELECT COUNT_BIG(*) reputacion_esperada FROM MuseosLatam_Origen.stg.lugar WHERE stars<>'' OR reviews<>'';
SELECT sk_periodo,precision_observacion,COUNT_BIG(*) observaciones FROM mart.fact_reputacion_lugar GROUP BY sk_periodo,precision_observacion;
SELECT COUNT_BIG(*) pesos_invalidos FROM mart.fact_resena_dimension WHERE peso<>1;
SELECT COUNT_BIG(*) geografia_inconsistente FROM mart.fact_resena f JOIN mart.dim_lugar l ON l.sk_lugar=f.sk_lugar WHERE f.sk_geografia<>l.sk_geografia OR f.codigo_pais<>l.codigo_pais;
SELECT MAX(DATALENGTH(texto_resena)/2) maximo_unidades_utf16,SUM(CASE WHEN CHARINDEX(CHAR(10),texto_resena)>0 THEN CONVERT(bigint,1) ELSE 0 END) multilinea FROM mart.fact_resena;
SELECT name,is_disabled,is_not_trusted FROM sys.foreign_keys;
SELECT * FROM aud.ejecucion ORDER BY id;
-- Diferencias de conteos entre las últimas ejecuciones: deben ser 0.
WITH e AS(SELECT id,informe,LAG(informe) OVER(ORDER BY id) previo FROM aud.ejecucion WHERE estado='EJECUTADO_Y_VERIFICADO')
SELECT e.id,j.[key] tabla,CONVERT(bigint,j.value)-CONVERT(bigint,p.value) delta
FROM e CROSS APPLY OPENJSON(e.informe,'$.conteos') j CROSS APPLY OPENJSON(e.previo,'$.conteos') p
WHERE j.[key]=p.[key];
-- Catálogo editorial vigente y límites de uso tras la revisión semántica.
SELECT * FROM mart.v_catalogo_topicos ORDER BY codigo_topico;
SELECT * FROM mart.v_cobertura_tematica ORDER BY codigo_pais;
