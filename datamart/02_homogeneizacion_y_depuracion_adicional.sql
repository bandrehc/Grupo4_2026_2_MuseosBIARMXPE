-- Homogeneización geográfica y depuración adicional del datamart (idempotente). Ejecutar DESPUÉS de 01_depuracion_columnas.sql.
-- Hacer BACKUP antes (ver datamart/README.md).
--  A) Geografía: nivel3_nombre '' -> NULL (Argentina/México no tienen nivel 3; ya era NULL en nivel3_tipo); codigo_nativo de Perú sin el ".0" residual.
--     No se modifica nk_geografia (hash de la clave natural) ni ninguna clave sustituta.
--  B) Campos redundantes: p_negativo, p_neutro, p_positivo, confianza_sentimiento (fact_resena); es_positiva/es_negativa/es_neutra (dim_rating);
--     trimestre, mes_nombre (dim_tiempo); pais_iso3 (dim_geografia). Todos derivables de otros campos o sin uso analítico.
--  C) Idioma: se elimina fact_resena.sk_idioma y la tabla mart.dim_idioma (el corpus es español; el detector de idioma es poco fiable en textos cortos).
USE MuseosLatam_Datamart;
GO
-- A) Geografía (nivel3_nombre era NOT NULL: se vuelve anulable, sin índices que dependan de ella)
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('mart.dim_geografia') AND name='nivel3_nombre' AND is_nullable=0)
  ALTER TABLE mart.dim_geografia ALTER COLUMN nivel3_nombre nvarchar(300) COLLATE Latin1_General_100_BIN2 NULL;
GO
UPDATE mart.dim_geografia SET nivel3_nombre=NULL WHERE nivel3_nombre=N'';
UPDATE mart.dim_geografia SET codigo_nativo=LEFT(codigo_nativo,LEN(codigo_nativo)-2) WHERE codigo_nativo LIKE N'%[0-9].0';
GO
-- B/C) 1) Vista que usa f.* y las columnas a eliminar: se reescribe sin ellas
IF EXISTS (SELECT 1 FROM sys.sql_modules WHERE object_id=OBJECT_ID('mart.v_resena_completa') AND (definition LIKE '%idioma%' OR definition LIKE '%trimestre%'))
EXEC('ALTER VIEW mart.v_resena_completa AS
SELECT f.*,l.nk_place_id,l.nombre museo,l.categoria_normalizada,g.pais_nombre,g.nivel1_nombre,g.nivel2_nombre,g.nivel3_nombre,
t.anio,t.mes,t.anio_mes,t.es_mes_determinado,t.etapa,
p.etiqueta perfil_autor,x.etiqueta extension_resena,a.etiqueta antiguedad_resena,d.etiqueta presencia_digital,
s.nk_codigo sentimiento,s.etiqueta sentimiento_etiqueta
FROM mart.fact_resena f
JOIN mart.dim_lugar l ON l.sk_lugar=f.sk_lugar
JOIN mart.dim_geografia g ON g.sk_geografia=f.sk_geografia
JOIN mart.dim_tiempo t ON t.sk_periodo=f.sk_periodo
JOIN mart.dim_perfil_autor p ON p.sk_perfil_autor=f.sk_perfil_autor
JOIN mart.dim_extension_resena x ON x.sk_extension_resena=f.sk_extension_resena
JOIN mart.dim_antiguedad_resena a ON a.sk_antiguedad_resena=f.sk_antiguedad_resena
JOIN mart.dim_presencia_digital d ON d.sk_presencia_digital=f.sk_presencia_digital
JOIN mart.dim_sentimiento s ON s.sk_sentimiento=f.sk_sentimiento');
GO
-- 2) Restricciones que dependen de las columnas (FK de sk_idioma, DEFAULT y CHECK de columna)
DECLARE @c TABLE(t sysname,col sysname);
INSERT @c VALUES ('fact_resena','sk_idioma'),('fact_resena','p_negativo'),('fact_resena','p_neutro'),('fact_resena','p_positivo'),('fact_resena','confianza_sentimiento'),
 ('dim_rating','es_positiva'),('dim_rating','es_negativa'),('dim_rating','es_neutra'),('dim_tiempo','trimestre'),('dim_tiempo','mes_nombre'),('dim_geografia','pais_iso3');
DECLARE @s nvarchar(max)=N'';
SELECT @s+=N'ALTER TABLE mart.'+QUOTENAME(c.t)+N' DROP CONSTRAINT '+QUOTENAME(dc.name)+N';'
FROM @c c JOIN sys.default_constraints dc ON dc.parent_object_id=OBJECT_ID('mart.'+c.t) AND COL_NAME(dc.parent_object_id,dc.parent_column_id)=c.col;
SELECT @s+=N'ALTER TABLE mart.'+QUOTENAME(c.t)+N' DROP CONSTRAINT '+QUOTENAME(k.name)+N';'
FROM @c c JOIN sys.check_constraints k ON k.parent_object_id=OBJECT_ID('mart.'+c.t) AND (k.parent_column_id=COLUMNPROPERTY(OBJECT_ID('mart.'+c.t),c.col,'ColumnId') OR k.definition LIKE N'%[[]'+c.col+N']%');
SELECT @s+=N'ALTER TABLE mart.fact_resena DROP CONSTRAINT '+QUOTENAME(fk.name)+N';'
FROM sys.foreign_keys fk WHERE fk.parent_object_id=OBJECT_ID('mart.fact_resena') AND fk.referenced_object_id=OBJECT_ID('mart.dim_idioma');
EXEC sp_executesql @s;
-- 3) Columnas
SET @s=N'';
SELECT @s+=N'ALTER TABLE mart.'+QUOTENAME(t)+N' DROP COLUMN '+QUOTENAME(col)+N';' FROM @c WHERE COL_LENGTH('mart.'+t,col) IS NOT NULL;
EXEC sp_executesql @s;
GO
-- 4) Tabla de idioma
DROP TABLE IF EXISTS mart.dim_idioma;
GO
-- 5) Refrescar metadatos de las vistas (las que usan f.*)
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
