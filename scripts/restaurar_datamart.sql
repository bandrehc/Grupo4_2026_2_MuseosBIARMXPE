-- Restauración manual del datamart en SQL Server 2019 o posterior (Windows o Linux), sin Docker.
-- 1) Copie data\MuseosLatam_Datamart_depurado_20261108.bak a una carpeta que el SERVICIO de SQL Server pueda leer.
-- 2) Edite solo @Bak. 3) Ejecute en SSMS / Azure Data Studio / sqlcmd con un usuario con permiso de restauración.
-- No sobrescribe: si la base ya existe se detiene (no use WITH REPLACE).
USE master;
IF TRY_CONVERT(int,SERVERPROPERTY('ProductMajorVersion'))<15 THROW 50001,'Se requiere SQL Server 2019 o posterior.',1;
IF DB_ID(N'MuseosLatam_Datamart') IS NOT NULL THROW 50002,'Ya existe MuseosLatam_Datamart; no se sobrescribe.',1;
DECLARE @Bak nvarchar(4000)=N'C:\CAMBIAR\MuseosLatam_Datamart_depurado_20261108.bak';
DECLARE @Data nvarchar(4000)=CONVERT(nvarchar(4000),SERVERPROPERTY('InstanceDefaultDataPath'));
DECLARE @Log  nvarchar(4000)=CONVERT(nvarchar(4000),SERVERPROPERTY('InstanceDefaultLogPath'));
DECLARE @sep nchar(1)=IIF(@Data LIKE N'%/%',N'/',N'\');
IF RIGHT(@Data,1)<>@sep SET @Data+=@sep; IF RIGHT(@Log,1)<>@sep SET @Log+=@sep;
DECLARE @D nvarchar(4000)=@Data+N'MuseosLatam_Datamart.mdf', @L nvarchar(4000)=@Log+N'MuseosLatam_Datamart_log.ldf';
RESTORE VERIFYONLY FROM DISK=@Bak WITH CHECKSUM;
RESTORE DATABASE [MuseosLatam_Datamart] FROM DISK=@Bak
  WITH CHECKSUM,RECOVERY,MOVE N'MuseosLatam_Datamart' TO @D,MOVE N'MuseosLatam_Datamart_log' TO @L,STATS=10;
-- Comprobación rápida (esperado: 1.143.877 reseñas, 233.556 pertenencias, 6.286 reputaciones)
SELECT (SELECT COUNT_BIG(*) FROM MuseosLatam_Datamart.mart.fact_resena) resenas,
       (SELECT COUNT_BIG(*) FROM MuseosLatam_Datamart.mart.fact_resena_dimension) pertenencias,
       (SELECT COUNT_BIG(*) FROM MuseosLatam_Datamart.mart.fact_reputacion_lugar) reputaciones;
