-- Ejecutado por aplicar_revision.py en transacción local que abarca origen y destino.
-- Los nombres se sustituyen solo por los nombres internos comprobados de estas bases.
IF NOT EXISTS(SELECT 1 FROM [{{ORIGEN}}].sys.schemas WHERE name='curado')
 EXEC [{{ORIGEN}}].sys.sp_executesql N'CREATE SCHEMA curado AUTHORIZATION dbo';
IF OBJECT_ID('[{{ORIGEN}}].curado.catalogo_topicos') IS NULL
CREATE TABLE [{{ORIGEN}}].curado.catalogo_topicos(
 version_revision varchar(80) NOT NULL,codigo_topico nvarchar(100) NOT NULL,version_modelo nvarchar(100) NOT NULL,
 etiqueta nvarchar(500) NOT NULL,descripcion nvarchar(max) NOT NULL,criterios_inclusion nvarchar(max) NOT NULL,criterios_exclusion nvarchar(max) NOT NULL,
 limitaciones nvarchar(max) NOT NULL,palabras_clave nvarchar(max) NOT NULL,validacion_etiqueta nvarchar(100) NOT NULL,apto_analisis_tematico bit NOT NULL,
 muestra_n int NOT NULL,coherentes_n int NOT NULL,parciales_n int NOT NULL,no_coherentes_n int NOT NULL,soporte_muestral decimal(6,4) NOT NULL,
 metodo_revision nvarchar(500) NOT NULL,detalle_paises nvarchar(max) NOT NULL,etiqueta_anterior nvarchar(500) NOT NULL,
 evidencia_sha256 char(64) NOT NULL,registrado_utc datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),
 PRIMARY KEY(version_revision,codigo_topico,version_modelo),CHECK(muestra_n=coherentes_n+parciales_n+no_coherentes_n),CHECK(soporte_muestral BETWEEN 0 AND 1));
IF OBJECT_ID('[{{ORIGEN}}].curado.evaluacion_topico') IS NULL
CREATE TABLE [{{ORIGEN}}].curado.evaluacion_topico(
 version_revision varchar(80) NOT NULL,codigo_topico nvarchar(100) NOT NULL,codigo_pais nvarchar(16) NOT NULL,numero int NOT NULL,
 id_review nvarchar(160) NOT NULL,source_row bigint NOT NULL,sha256_texto char(64) NOT NULL,juicio char(1) NOT NULL CHECK(juicio IN ('C','P','N')),criterio nvarchar(250) NOT NULL,
 PRIMARY KEY(version_revision,codigo_topico,codigo_pais,numero));
IF OBJECT_ID('[{{ORIGEN}}].curado.evaluacion_sentimiento') IS NULL
CREATE TABLE [{{ORIGEN}}].curado.evaluacion_sentimiento(
 version_revision varchar(80) NOT NULL,numero int NOT NULL,id_review nvarchar(160) NOT NULL,source_row bigint NOT NULL,codigo_pais nvarchar(16) NOT NULL,
 sentimiento_original nvarchar(100) NOT NULL,estado_original nvarchar(100) NOT NULL,sha256_texto char(64) NOT NULL,juicio char(1) NOT NULL,dictamen nvarchar(300) NOT NULL,
 PRIMARY KEY(version_revision,numero));
IF OBJECT_ID('aud.revision_semantica') IS NULL
CREATE TABLE aud.revision_semantica(version_revision varchar(80) PRIMARY KEY,evidencia_sha256 char(64) NOT NULL,aplicado_utc datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),revisor nvarchar(200) NOT NULL,validacion_humana bit NOT NULL CHECK(validacion_humana=0),respaldo nvarchar(max) NOT NULL);
GO
IF COL_LENGTH('mart.dim_dimension_latente','version_revision') IS NULL
ALTER TABLE mart.dim_dimension_latente ADD version_revision varchar(80) NULL,criterios_inclusion nvarchar(max) NULL,criterios_exclusion nvarchar(max) NULL,
 limitaciones nvarchar(max) NULL,apto_analisis_tematico bit NULL,muestra_revisada int NULL,soporte_muestral decimal(6,4) NULL,metodo_revision nvarchar(500) NULL;
