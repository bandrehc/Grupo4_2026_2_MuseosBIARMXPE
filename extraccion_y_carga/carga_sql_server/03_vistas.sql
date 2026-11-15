USE [MuseosLatam_Datamart];
GO
CREATE OR ALTER VIEW mart.v_resena_completa AS
SELECT f.*,l.nk_place_id,l.nombre museo,l.categoria_normalizada,g.pais_nombre,g.nivel1_nombre,g.nivel2_nombre,g.nivel3_nombre,
t.anio,t.mes,t.trimestre,t.anio_mes,t.es_mes_determinado,t.etapa,
p.etiqueta perfil_autor,x.etiqueta extension_resena,a.etiqueta antiguedad_resena,d.etiqueta presencia_digital,
i.nk_codigo codigo_idioma,i.nombre idioma,s.nk_codigo sentimiento,s.etiqueta sentimiento_etiqueta
FROM mart.fact_resena f
JOIN mart.dim_lugar l ON l.sk_lugar=f.sk_lugar
JOIN mart.dim_geografia g ON g.sk_geografia=f.sk_geografia
JOIN mart.dim_tiempo t ON t.sk_periodo=f.sk_periodo
JOIN mart.dim_perfil_autor p ON p.sk_perfil_autor=f.sk_perfil_autor
JOIN mart.dim_extension_resena x ON x.sk_extension_resena=f.sk_extension_resena
JOIN mart.dim_antiguedad_resena a ON a.sk_antiguedad_resena=f.sk_antiguedad_resena
JOIN mart.dim_presencia_digital d ON d.sk_presencia_digital=f.sk_presencia_digital
JOIN mart.dim_idioma i ON i.sk_idioma=f.sk_idioma
JOIN mart.dim_sentimiento s ON s.sk_sentimiento=f.sk_sentimiento;
GO
CREATE OR ALTER VIEW mart.v_kpi_museo AS
SELECT l.clave_lugar,l.nombre,l.categoria_normalizada,g.pais_nombre,g.nivel1_nombre,
COUNT_BIG(*) n_resenas,COUNT_BIG(f.rating) n_ratings,
SUM(CONVERT(bigint,f.rating)) suma_rating,
1.0*SUM(CONVERT(bigint,f.rating))/NULLIF(COUNT_BIG(f.rating),0) rating_promedio,
SUM(CONVERT(bigint,f.tiene_texto)) n_con_texto,
SUM(CASE WHEN f.rating<=2 THEN CONVERT(bigint,1) ELSE 0 END) n_ratings_negativos,
SUM(CASE WHEN f.tiene_texto=1 THEN CONVERT(bigint,f.cantidad_palabras) ELSE 0 END) palabras_con_texto
FROM mart.fact_resena f JOIN mart.dim_lugar l ON l.sk_lugar=f.sk_lugar JOIN mart.dim_geografia g ON g.sk_geografia=f.sk_geografia
GROUP BY l.clave_lugar,l.nombre,l.categoria_normalizada,g.pais_nombre,g.nivel1_nombre;
GO
CREATE OR ALTER VIEW mart.v_tendencia_mensual AS
SELECT f.codigo_pais,t.anio_mes,COUNT_BIG(*) n_resenas,COUNT_BIG(f.rating) n_ratings,
SUM(CONVERT(bigint,f.rating)) suma_rating,
1.0*SUM(CONVERT(bigint,f.rating))/NULLIF(COUNT_BIG(f.rating),0) rating_promedio
FROM mart.fact_resena f JOIN mart.dim_tiempo t ON t.sk_periodo=f.sk_periodo
WHERE t.es_mes_determinado=1 GROUP BY f.codigo_pais,t.anio_mes;
GO
CREATE OR ALTER VIEW mart.v_tendencia_anual AS
SELECT f.codigo_pais,t.anio,COUNT_BIG(*) n_resenas,COUNT_BIG(f.rating) n_ratings,
SUM(CONVERT(bigint,f.rating)) suma_rating,
1.0*SUM(CONVERT(bigint,f.rating))/NULLIF(COUNT_BIG(f.rating),0) rating_promedio
FROM mart.fact_resena f JOIN mart.dim_tiempo t ON t.sk_periodo=f.sk_periodo
WHERE t.anio IS NOT NULL GROUP BY f.codigo_pais,t.anio;
GO
CREATE OR ALTER VIEW mart.v_dimension_satisfaccion AS
SELECT f.codigo_pais,d.nk_codigo,d.version_modelo,d.etiqueta,COUNT_BIG(*) n_asignadas,
SUM(CASE WHEN f.rating IS NOT NULL THEN w.peso ELSE 0 END) peso_con_rating,
SUM(f.rating*w.peso)/NULLIF(SUM(CASE WHEN f.rating IS NOT NULL THEN w.peso ELSE 0 END),0) rating_ponderado
FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena
JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente
GROUP BY f.codigo_pais,d.nk_codigo,d.version_modelo,d.etiqueta;
GO
CREATE OR ALTER VIEW mart.v_reputacion_territorial AS
SELECT g.pais_nombre,g.nivel1_nombre,f.precision_observacion,COUNT_BIG(*) n_fichas_observadas,
SUM(f.n_valoraciones_google) n_valoraciones_google,
SUM(f.rating_promedio_google*f.n_valoraciones_google)/NULLIF(SUM(CASE WHEN f.rating_promedio_google IS NOT NULL THEN f.n_valoraciones_google END),0) rating_google_ponderado
FROM mart.fact_reputacion_lugar f JOIN mart.dim_geografia g ON g.sk_geografia=f.sk_geografia
GROUP BY g.pais_nombre,g.nivel1_nombre,f.precision_observacion;
