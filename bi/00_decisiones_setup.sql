-- Capa de decisiones de curaduría de lugares (idempotente; no borra datos existentes).
-- Se ejecuta una vez (o cuantas veces se quiera) ANTES de 01_bi_setup.sql.
-- 01_bi_setup.sql reconstruye toda la capa BI leyendo estas tablas; ellas no se reconstruyen.
USE MuseosLatam_Datamart;
GO
IF SCHEMA_ID('bi') IS NULL EXEC('CREATE SCHEMA bi');
GO
-- Categorías permitidas para reclasificar (se siembran desde el datamart; sin la categoría vacía)
IF OBJECT_ID('bi.categoria_valida') IS NULL
  CREATE TABLE bi.categoria_valida(categoria nvarchar(200) NOT NULL PRIMARY KEY);
INSERT bi.categoria_valida(categoria)
SELECT DISTINCT l.categoria_normalizada FROM mart.dim_lugar l
WHERE l.categoria_normalizada<>N'' AND NOT EXISTS (SELECT 1 FROM bi.categoria_valida c WHERE c.categoria=l.categoria_normalizada);
GO
-- Un lote = una carga de un archivo de decisiones
IF OBJECT_ID('bi.decision_lote') IS NULL
  CREATE TABLE bi.decision_lote(
    id_lote int IDENTITY(1,1) PRIMARY KEY,
    archivo nvarchar(260) NOT NULL, sha256 char(64) NOT NULL,
    cargado_utc datetime2 NOT NULL DEFAULT SYSUTCDATETIME(), cargado_por sysname NOT NULL DEFAULT SUSER_SNAME(),
    filas_con_decision int NOT NULL, n_excluir int NOT NULL, n_reclasificar int NOT NULL, n_mantener int NOT NULL, n_cambios int NOT NULL,
    notas nvarchar(500) NULL);
GO
-- Estado vigente: una fila por lugar con decisión. Sin FK a mart.dim_lugar a propósito: una recarga del ETL no debe quedar bloqueada;
-- las decisiones huérfanas se detectan con bi.v_decision_huerfana.
IF OBJECT_ID('bi.lugar_decision') IS NULL
  CREATE TABLE bi.lugar_decision(
    sk_lugar bigint NOT NULL PRIMARY KEY,
    decision varchar(12) NOT NULL CONSTRAINT ck_decision CHECK (decision IN ('Mantener','Excluir','Reclasificar')),
    categoria_nueva nvarchar(200) NULL CONSTRAINT fk_decision_categoria REFERENCES bi.categoria_valida(categoria),
    categoria_original nvarchar(200) NULL,      -- categoría del datamart al momento de decidir (auditoría)
    nombre_lugar nvarchar(1000) NULL,           -- nombre al momento de decidir (legibilidad)
    comentario nvarchar(1000) NULL,
    id_lote int NOT NULL REFERENCES bi.decision_lote(id_lote),
    actualizado_utc datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT ck_reclas_cat CHECK ((decision='Reclasificar' AND categoria_nueva IS NOT NULL) OR (decision<>'Reclasificar' AND categoria_nueva IS NULL)));
GO
-- Historial solo de inserción: cada cambio de decisión deja un registro (permite auditar y deshacer a mano)
IF OBJECT_ID('bi.lugar_decision_hist') IS NULL
  CREATE TABLE bi.lugar_decision_hist(
    id_hist bigint IDENTITY(1,1) PRIMARY KEY, sk_lugar bigint NOT NULL,
    decision_anterior varchar(12) NULL, categoria_anterior nvarchar(200) NULL,
    decision_nueva varchar(12) NOT NULL, categoria_nueva nvarchar(200) NULL, comentario nvarchar(1000) NULL,
    id_lote int NOT NULL REFERENCES bi.decision_lote(id_lote), fecha_utc datetime2 NOT NULL DEFAULT SYSUTCDATETIME());
GO
-- Metadatos de la última construcción de la capa BI (los lee el dashboard para mostrar transparencia)
IF OBJECT_ID('bi.meta') IS NULL
  CREATE TABLE bi.meta(clave varchar(50) NOT NULL PRIMARY KEY, valor nvarchar(500) NULL);
GO
CREATE OR ALTER VIEW bi.v_decision_huerfana AS
SELECT d.sk_lugar,d.decision,d.nombre_lugar,
  CASE WHEN NOT EXISTS (SELECT 1 FROM mart.dim_lugar l WHERE l.sk_lugar=d.sk_lugar) THEN 'El lugar ya no existe en mart.dim_lugar'
       ELSE 'El lugar existe pero no tiene reseñas' END motivo
FROM bi.lugar_decision d
WHERE NOT EXISTS (SELECT 1 FROM mart.dim_lugar l WHERE l.sk_lugar=d.sk_lugar)
   OR NOT EXISTS (SELECT 1 FROM mart.fact_resena f WHERE f.sk_lugar=d.sk_lugar);
GO
-- Mínimo privilegio: el usuario del dashboard no necesita ver comentarios internos de curaduría
IF DATABASE_PRINCIPAL_ID('dashly_ro') IS NOT NULL
BEGIN
  DENY SELECT ON bi.lugar_decision TO dashly_ro;
  DENY SELECT ON bi.lugar_decision_hist TO dashly_ro;
  DENY SELECT ON bi.decision_lote TO dashly_ro;
END
GO
