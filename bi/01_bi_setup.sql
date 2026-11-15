-- Capa BI (idempotente; se reconstruye completa). Base: MuseosLatam_Datamart. No modifica mart.*.
-- Requiere 00_decisiones_setup.sql. Aplica las decisiones de curaduría de bi.lugar_decision:
--   Excluir      -> el lugar no entra a bi.lugar ni a ningún agregado/vista (sus reseñas dejan de contarse en el dashboard)
--   Reclasificar -> bi.lugar.categoria toma la categoría nueva (la original queda en categoria_original)
--   Mantener / sin decisión -> sin cambios
USE MuseosLatam_Datamart;
GO
IF OBJECT_ID('bi.lugar_decision') IS NULL OR OBJECT_ID('bi.meta') IS NULL
  THROW 50010, 'Ejecute primero 00_decisiones_setup.sql', 1;
GO
DROP TABLE IF EXISTS bi.topico_catalogo, bi.agg_topico_sent_anio, bi.agg_lugar_topico_anio, bi.agg_lugar_anio, bi.lugar;
DROP VIEW IF EXISTS bi.v_control_reconciliacion, bi.v_resena, bi.v_benchmark_lugar, bi.v_pais_anio, bi.v_topico_pais_anio;
GO
CREATE TABLE bi.lugar(sk_lugar bigint PRIMARY KEY, nombre nvarchar(1000), categoria nvarchar(200), pais nvarchar(100), codigo_pais nvarchar(16),
  region nvarchar(300), subregion nvarchar(300), latitud decimal(12,9), longitud decimal(12,9),
  categoria_original nvarchar(200), reclasificado bit NOT NULL);
INSERT bi.lugar
SELECT l.sk_lugar,l.nombre,COALESCE(d.categoria_nueva,l.categoria_normalizada),g.pais_nombre,g.codigo_pais,g.nivel1_nombre,g.nivel2_nombre,l.latitud,l.longitud,
 l.categoria_normalizada,CASE WHEN d.decision='Reclasificar' THEN 1 ELSE 0 END
FROM mart.dim_lugar l JOIN mart.dim_geografia g ON g.sk_geografia=l.sk_geografia
LEFT JOIN bi.lugar_decision d ON d.sk_lugar=l.sk_lugar
WHERE l.sk_lugar IN (SELECT DISTINCT sk_lugar FROM mart.fact_resena)
  AND COALESCE(d.decision,'Mantener')<>'Excluir';
-- anio 0 = fecha no determinada
CREATE TABLE bi.agg_lugar_anio(sk_lugar bigint, anio smallint, n_resenas int, n_ratings int, suma_rating int, n_rating_neg int,
  n_con_texto int, n_pos int, n_neu int, n_neg int, n_sent_nc int,
  n_r1 int, n_r2 int, n_r3 int, n_r4 int, n_r5 int, PRIMARY KEY(sk_lugar,anio));
INSERT bi.agg_lugar_anio
SELECT f.sk_lugar,ISNULL(t.anio,0),COUNT(*),COUNT(f.rating),SUM(CONVERT(int,f.rating)),SUM(CASE WHEN f.rating<=2 THEN 1 ELSE 0 END),
 SUM(CONVERT(int,f.tiene_texto)),
 SUM(CASE WHEN s.etiqueta='Positivo' THEN 1 ELSE 0 END),SUM(CASE WHEN s.etiqueta='Neutro' THEN 1 ELSE 0 END),
 SUM(CASE WHEN s.etiqueta='Negativo' THEN 1 ELSE 0 END),SUM(CASE WHEN s.etiqueta='No clasificado' THEN 1 ELSE 0 END),
 SUM(CASE WHEN f.rating=1 THEN 1 ELSE 0 END),SUM(CASE WHEN f.rating=2 THEN 1 ELSE 0 END),SUM(CASE WHEN f.rating=3 THEN 1 ELSE 0 END),SUM(CASE WHEN f.rating=4 THEN 1 ELSE 0 END),SUM(CASE WHEN f.rating=5 THEN 1 ELSE 0 END)
FROM mart.fact_resena f JOIN bi.lugar bl ON bl.sk_lugar=f.sk_lugar
JOIN mart.dim_tiempo t ON t.sk_periodo=f.sk_periodo JOIN mart.dim_sentimiento s ON s.sk_sentimiento=f.sk_sentimiento
GROUP BY f.sk_lugar,ISNULL(t.anio,0);
-- Solo tópicos aptos; el puente es N:M (una reseña puede tener varios tópicos): no sumar entre tópicos
CREATE TABLE bi.agg_lugar_topico_anio(sk_lugar bigint, anio smallint, codigo_topico nvarchar(100), topico nvarchar(500), n_resenas int, PRIMARY KEY(sk_lugar,anio,codigo_topico));
INSERT bi.agg_lugar_topico_anio
SELECT f.sk_lugar,ISNULL(t.anio,0),d.nk_codigo,d.etiqueta,COUNT(*)
FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena JOIN bi.lugar bl ON bl.sk_lugar=f.sk_lugar
JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente AND d.apto_analisis_tematico=1
JOIN mart.dim_tiempo t ON t.sk_periodo=f.sk_periodo
GROUP BY f.sk_lugar,ISNULL(t.anio,0),d.nk_codigo,d.etiqueta;
-- tópico apto x sentimiento de la reseña (para sunburst); una reseña puede aparecer en varios tópicos
CREATE TABLE bi.agg_topico_sent_anio(pais nvarchar(100), categoria nvarchar(200), anio smallint, topico nvarchar(500), sentimiento nvarchar(50), n int);
INSERT bi.agg_topico_sent_anio
SELECT l.pais,l.categoria,ISNULL(t.anio,0),d.etiqueta,s.etiqueta,COUNT(*)
FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena JOIN bi.lugar l ON l.sk_lugar=f.sk_lugar
JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente AND d.apto_analisis_tematico=1
JOIN mart.dim_tiempo t ON t.sk_periodo=f.sk_periodo JOIN mart.dim_sentimiento s ON s.sk_sentimiento=f.sk_sentimiento
GROUP BY l.pais,l.categoria,ISNULL(t.anio,0),d.etiqueta,s.etiqueta;
GO
CREATE VIEW bi.v_pais_anio AS
SELECT l.pais,l.categoria,a.anio,SUM(a.n_resenas) n_resenas,SUM(a.suma_rating)*1.0/NULLIF(SUM(a.n_ratings),0) rating_prom,
 SUM(a.n_rating_neg)*1.0/NULLIF(SUM(a.n_ratings),0) pct_rating_bajo,
 SUM(a.n_pos)*1.0/NULLIF(SUM(a.n_pos+a.n_neu+a.n_neg),0) pct_pos,SUM(a.n_neg)*1.0/NULLIF(SUM(a.n_pos+a.n_neu+a.n_neg),0) pct_neg,
 SUM(a.n_con_texto) n_con_texto
FROM bi.agg_lugar_anio a JOIN bi.lugar l ON l.sk_lugar=a.sk_lugar GROUP BY l.pais,l.categoria,a.anio;
GO
CREATE VIEW bi.v_topico_pais_anio AS
SELECT l.pais,l.categoria,a.anio,a.codigo_topico,a.topico,SUM(a.n_resenas) n_resenas
FROM bi.agg_lugar_topico_anio a JOIN bi.lugar l ON l.sk_lugar=a.sk_lugar GROUP BY l.pais,l.categoria,a.anio,a.codigo_topico,a.topico;
GO
-- Benchmark: rating suavizado (prior m=20 resenas con media del grupo), percentiles en pais+categoria; solo lugares con >=30 ratings
CREATE VIEW bi.v_benchmark_lugar AS
WITH t AS (SELECT sk_lugar,SUM(n_resenas) n_resenas,SUM(n_ratings) n_ratings,SUM(suma_rating) suma_rating,SUM(n_rating_neg) n_rating_neg,
  SUM(n_pos) n_pos,SUM(n_neg) n_neg,SUM(n_pos+n_neu+n_neg) n_sent FROM bi.agg_lugar_anio GROUP BY sk_lugar),
g AS (SELECT l.pais,l.categoria,SUM(t.suma_rating)*1.0/SUM(t.n_ratings) media_grupo FROM t JOIN bi.lugar l ON l.sk_lugar=t.sk_lugar GROUP BY l.pais,l.categoria),
b AS (SELECT l.*,t.n_resenas,t.n_ratings,t.suma_rating*1.0/NULLIF(t.n_ratings,0) rating_prom,
  (t.suma_rating+20*g.media_grupo)/(t.n_ratings+20.0) rating_suavizado,
  t.n_rating_neg*1.0/NULLIF(t.n_ratings,0) pct_rating_bajo,t.n_pos*1.0/NULLIF(t.n_sent,0) pct_pos,t.n_neg*1.0/NULLIF(t.n_sent,0) pct_neg,g.media_grupo
  FROM t JOIN bi.lugar l ON l.sk_lugar=t.sk_lugar JOIN g ON g.pais=l.pais AND g.categoria=l.categoria)
SELECT b.*,CASE WHEN n_ratings>=30 THEN PERCENT_RANK() OVER(PARTITION BY pais,categoria,CASE WHEN n_ratings>=30 THEN 1 ELSE 0 END ORDER BY rating_suavizado) END pct_rank_pares,
 CASE WHEN n_ratings>=30 THEN 'comparable' ELSE 'muestra insuficiente (<30 ratings)' END estado_muestra
FROM b;
GO
-- Reseñas individuales (consultar siempre con filtro por sk_lugar y TOP). Solo tópicos aptos.
CREATE VIEW bi.v_resena AS
SELECT f.sk_resena,f.sk_lugar,ISNULL(t.anio,0) anio,f.rating,s.etiqueta sentimiento,f.puntaje_sentimiento,f.estado_topicos,
 f.texto_resena,tp.topicos
FROM mart.fact_resena f JOIN mart.dim_tiempo t ON t.sk_periodo=f.sk_periodo JOIN mart.dim_sentimiento s ON s.sk_sentimiento=f.sk_sentimiento
JOIN bi.lugar bl ON bl.sk_lugar=f.sk_lugar
OUTER APPLY (SELECT STRING_AGG(CONVERT(nvarchar(max),d.etiqueta),N' · ') topicos FROM mart.fact_resena_dimension w
  JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente AND d.apto_analisis_tematico=1 WHERE w.sk_resena=f.sk_resena) tp
WHERE f.tiene_texto=1;
GO
-- Catálogo de tópicos (41 + desconocido): qué es apto para indicadores y con qué límites (para la pestaña Metodología)
CREATE TABLE bi.topico_catalogo(codigo nvarchar(100) PRIMARY KEY, etiqueta nvarchar(500), apto bit, muestra_revisada int, soporte_muestral decimal(6,4),
  descripcion nvarchar(max), limitaciones nvarchar(max));
INSERT bi.topico_catalogo
SELECT nk_codigo,etiqueta,ISNULL(apto_analisis_tematico,0),muestra_revisada,soporte_muestral,descripcion,limitaciones
FROM mart.dim_dimension_latente WHERE sk_dimension_latente<>-1;
GO
-- Control de reconciliación: todo debe cuadrar con el datamart descontando solo lo excluido por decisión
CREATE VIEW bi.v_control_reconciliacion AS
WITH x AS (
 SELECT
  (SELECT COUNT_BIG(*) FROM mart.fact_resena) resenas_datamart,
  (SELECT COUNT_BIG(*) FROM mart.fact_resena f JOIN bi.lugar_decision d ON d.sk_lugar=f.sk_lugar AND d.decision='Excluir') resenas_excluidas,
  (SELECT CONVERT(bigint,ISNULL(SUM(n_resenas),0)) FROM bi.agg_lugar_anio) resenas_bi,
  (SELECT COUNT_BIG(*) FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena
     JOIN mart.dim_dimension_latente dl ON dl.sk_dimension_latente=w.sk_dimension_latente AND dl.apto_analisis_tematico=1) menciones_datamart,
  (SELECT COUNT_BIG(*) FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena
     JOIN mart.dim_dimension_latente dl ON dl.sk_dimension_latente=w.sk_dimension_latente AND dl.apto_analisis_tematico=1
     JOIN bi.lugar_decision d ON d.sk_lugar=f.sk_lugar AND d.decision='Excluir') menciones_excluidas,
  (SELECT CONVERT(bigint,ISNULL(SUM(n_resenas),0)) FROM bi.agg_lugar_topico_anio) menciones_bi,
  (SELECT CONVERT(bigint,ISNULL(SUM(n),0)) FROM bi.agg_topico_sent_anio) menciones_bi_sent,
  (SELECT COUNT_BIG(*) FROM bi.v_resena) resenas_texto_bi,
  (SELECT COUNT_BIG(*) FROM mart.fact_resena f WHERE f.tiene_texto=1 AND NOT EXISTS (SELECT 1 FROM bi.lugar_decision d WHERE d.sk_lugar=f.sk_lugar AND d.decision='Excluir')) resenas_texto_esperadas,
  (SELECT COUNT(*) FROM bi.lugar l WHERE EXISTS (SELECT 1 FROM bi.lugar_decision d WHERE d.sk_lugar=l.sk_lugar AND d.decision='Excluir')) excluidos_presentes_en_bi,
  (SELECT COUNT(*) FROM bi.v_decision_huerfana) decisiones_huerfanas)
SELECT *,
 resenas_datamart-resenas_excluidas-resenas_bi AS dif_resenas,
 menciones_datamart-menciones_excluidas-menciones_bi AS dif_menciones,
 menciones_bi-menciones_bi_sent AS dif_menciones_sent,
 resenas_texto_esperadas-resenas_texto_bi AS dif_resenas_texto,
 CASE WHEN resenas_datamart-resenas_excluidas=resenas_bi AND menciones_datamart-menciones_excluidas=menciones_bi AND menciones_bi=menciones_bi_sent
       AND resenas_texto_esperadas=resenas_texto_bi AND excluidos_presentes_en_bi=0 THEN 1 ELSE 0 END AS ok
FROM x;
GO
-- Metadatos de esta construcción (el dashboard los muestra)
DELETE bi.meta;
INSERT bi.meta(clave,valor) VALUES
 ('construido_utc',CONVERT(varchar(19),SYSUTCDATETIME(),120)),
 ('n_lugares',CONVERT(varchar(20),(SELECT COUNT(*) FROM bi.lugar))),
 ('n_resenas',CONVERT(varchar(20),(SELECT SUM(CONVERT(bigint,n_resenas)) FROM bi.agg_lugar_anio))),
 ('n_excluidos',CONVERT(varchar(20),(SELECT COUNT(*) FROM bi.lugar_decision WHERE decision='Excluir'))),
 ('n_reclasificados',CONVERT(varchar(20),(SELECT COUNT(*) FROM bi.lugar WHERE reclasificado=1))),
 ('n_mantener_revisados',CONVERT(varchar(20),(SELECT COUNT(*) FROM bi.lugar_decision WHERE decision='Mantener'))),
 ('ultimo_lote',CONVERT(varchar(20),(SELECT ISNULL(MAX(id_lote),0) FROM bi.decision_lote)));
GO
GRANT SELECT ON SCHEMA::bi TO dashly_ro;
IF DATABASE_PRINCIPAL_ID('dashly_ro') IS NOT NULL
BEGIN
  DENY SELECT ON bi.lugar_decision TO dashly_ro;
  DENY SELECT ON bi.lugar_decision_hist TO dashly_ro;
  DENY SELECT ON bi.decision_lote TO dashly_ro;
END
GO
