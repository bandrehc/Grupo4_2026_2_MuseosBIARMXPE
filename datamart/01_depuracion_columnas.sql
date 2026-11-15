-- Depuración del datamart: elimina columnas sin información (un solo valor en todas las filas, o siempre vacías).
-- Evidencia (perfilado de todas las columnas de mart.*): COUNT(DISTINCT)=1 o 100 % NULL.
-- Idempotente: cada paso comprueba si la columna ya no existe. Hacer BACKUP antes (ver datamart/README.md).
USE MuseosLatam_Datamart;
GO
-- 1) Vistas: se reescriben sin las columnas que se eliminan
IF EXISTS (SELECT 1 FROM sys.sql_modules WHERE object_id=OBJECT_ID('mart.v_catalogo_topicos') AND definition LIKE '%version_revision%')
EXEC('ALTER VIEW mart.v_catalogo_topicos AS
SELECT nk_codigo codigo_topico,version_modelo,etiqueta,descripcion,palabras_clave,
 validacion_etiqueta,apto_analisis_tematico,criterios_inclusion,criterios_exclusion,limitaciones,
 muestra_revisada,soporte_muestral,metodo_revision
FROM mart.dim_dimension_latente WHERE sk_dimension_latente<>-1');
GO
-- peso era siempre 1: el "peso con rating" es el número de asignaciones con rating y el promedio ponderado es el promedio simple
IF EXISTS (SELECT 1 FROM sys.sql_modules WHERE object_id=OBJECT_ID('mart.v_dimension_satisfaccion') AND definition LIKE '%peso%')
EXEC('ALTER VIEW mart.v_dimension_satisfaccion AS
SELECT f.codigo_pais,d.nk_codigo,d.version_modelo,d.etiqueta,d.validacion_etiqueta,d.apto_analisis_tematico,
COUNT_BIG(*) n_asignadas,COUNT_BIG(f.rating) n_con_rating,
AVG(CONVERT(float,f.rating)) rating_promedio
FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena
JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente
GROUP BY f.codigo_pais,d.nk_codigo,d.version_modelo,d.etiqueta,d.validacion_etiqueta,d.apto_analisis_tematico');
GO
IF EXISTS (SELECT 1 FROM sys.sql_modules WHERE object_id=OBJECT_ID('mart.v_reputacion_territorial') AND definition LIKE '%precision_observacion%')
EXEC('ALTER VIEW mart.v_reputacion_territorial AS
SELECT g.pais_nombre,g.nivel1_nombre,COUNT_BIG(*) n_fichas_observadas,
SUM(f.n_valoraciones_google) n_valoraciones_google,
SUM(f.rating_promedio_google*f.n_valoraciones_google)/NULLIF(SUM(CASE WHEN f.rating_promedio_google IS NOT NULL THEN f.n_valoraciones_google END),0) rating_google_ponderado
FROM mart.fact_reputacion_lugar f JOIN mart.dim_geografia g ON g.sk_geografia=f.sk_geografia
GROUP BY g.pais_nombre,g.nivel1_nombre');
GO
EXEC sp_refreshview 'mart.v_dimension_satisfaccion_revisada';
GO
-- 2) Restricciones que dependen de las columnas
DECLARE @s nvarchar(max)=N'';
SELECT @s+=N'ALTER TABLE mart.'+QUOTENAME(OBJECT_NAME(parent_object_id))+N' DROP CONSTRAINT '+QUOTENAME(name)+N';'
FROM sys.check_constraints WHERE name IN (SELECT name FROM sys.check_constraints WHERE definition LIKE '%[[]precision_observacion]%' OR definition LIKE '%[[]peso]%');
SELECT @s+=N'ALTER TABLE mart.'+QUOTENAME(OBJECT_NAME(parent_object_id))+N' DROP CONSTRAINT '+QUOTENAME(name)+N';'
FROM sys.default_constraints WHERE parent_object_id=OBJECT_ID('mart.dim_lugar') AND COL_NAME(parent_object_id,parent_column_id) IN ('es_vigente','version');
SELECT @s+=N'ALTER TABLE mart.fact_reputacion_lugar DROP CONSTRAINT '+QUOTENAME(fk.name)+N';'
FROM sys.foreign_keys fk WHERE fk.parent_object_id=OBJECT_ID('mart.fact_reputacion_lugar') AND EXISTS
 (SELECT 1 FROM sys.foreign_key_columns k WHERE k.constraint_object_id=fk.object_id AND COL_NAME(k.parent_object_id,k.parent_column_id)='sk_periodo');
-- la unicidad (sk_lugar, version_fuente) pasa a (sk_lugar): una ficha por lugar
SELECT @s+=N'ALTER TABLE mart.fact_reputacion_lugar DROP CONSTRAINT '+QUOTENAME(x.name)+N';'
FROM sys.indexes x WHERE x.object_id=OBJECT_ID('mart.fact_reputacion_lugar') AND x.is_unique_constraint=1
 AND EXISTS (SELECT 1 FROM sys.index_columns ic JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE ic.object_id=x.object_id AND ic.index_id=x.index_id AND c.name='version_fuente');
EXEC sp_executesql @s;
GO
IF COL_LENGTH('mart.fact_reputacion_lugar','version_fuente') IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='uq_fact_reputacion_lugar')
  ALTER TABLE mart.fact_reputacion_lugar ADD CONSTRAINT uq_fact_reputacion_lugar UNIQUE(sk_lugar);
GO
-- 3) Columnas
DECLARE @c TABLE(t sysname,col sysname);
INSERT @c VALUES ('dim_lugar','es_vigente'),('dim_lugar','version'),('dim_lugar','valido_desde'),('dim_lugar','valido_hasta'),
 ('fact_reputacion_lugar','fecha_observacion'),('fact_reputacion_lugar','precision_observacion'),('fact_reputacion_lugar','version_fuente'),('fact_reputacion_lugar','sk_periodo'),
 ('fact_resena','hash_fuente'),('fact_resena','version_modelo_topicos'),
 ('fact_resena_dimension','peso'),('fact_resena_dimension','es_dominante'),('fact_resena_dimension','hash_fuente'),
 ('dim_dimension_latente','version_revision');
DECLARE @s nvarchar(max)=N'';
SELECT @s+=N'ALTER TABLE mart.'+QUOTENAME(t)+N' DROP COLUMN '+QUOTENAME(col)+N';' FROM @c WHERE COL_LENGTH('mart.'+t,col) IS NOT NULL;
EXEC sp_executesql @s;
GO
-- 4) Vistas con SELECT * (p. ej. v_resena_completa usa f.*): refrescar metadatos
-- Cada vista por separado: una que dependa de la base de origen (mart.v_fuente_lugar), si no está restaurada, no debe detener el script.
DECLARE @v nvarchar(300);
DECLARE cv CURSOR LOCAL FAST_FORWARD FOR SELECT QUOTENAME(SCHEMA_NAME(schema_id))+N'.'+QUOTENAME(name) FROM sys.views WHERE SCHEMA_NAME(schema_id)='mart';
OPEN cv; FETCH NEXT FROM cv INTO @v;
WHILE @@FETCH_STATUS=0
BEGIN
  BEGIN TRY EXEC sp_refreshview @v; END TRY
  BEGIN CATCH PRINT N'Aviso: no se pudo refrescar '+@v+N' ('+ERROR_MESSAGE()+N')'; END CATCH
  FETCH NEXT FROM cv INTO @v;
END
CLOSE cv; DEALLOCATE cv;
GO
