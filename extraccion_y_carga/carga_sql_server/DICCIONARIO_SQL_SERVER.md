# Diccionario físico SQL Server

Generado desde `sys.columns` con `documentar.py`. Trazabilidad de cada columna CSV hasta su destino: `mapa_campos.csv`.

- **MuseosLatam_Datamart** (sección 1): esquema del datamart entregado en el respaldo `.bak`, con 3 hechos y 10 dimensiones; cada dimensión tiene un miembro -1 (desconocido).
- **MuseosLatam_Origen** (sección 2): base de origen de la carga (`stg` literal, `curado`, `aud`); no forma parte del respaldo entregado.

## 1. MuseosLatam_Datamart (datamart entregado)

### MuseosLatam_Datamart.aud.ejecucion

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| id | bigint | No | Campo de auditoría de ejecucion. |
| inicio | datetime2 | No | Campo de auditoría de ejecucion. |
| fin | datetime2 | Sí | Campo de auditoría de ejecucion. |
| estado | varchar(40) | No | Campo de auditoría de ejecucion. |
| informe | nvarchar(MAX) | Sí | Campo de auditoría de ejecucion. |

### MuseosLatam_Datamart.aud.fuente

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| tabla | varchar(40) | No | Campo de auditoría de fuente. |
| version | varchar(80) | No | Versión de la ficha observada. |
| sha256 | char(64) | No | Campo de auditoría de fuente. |
| filas | bigint | No | Campo de auditoría de fuente. |
| encabezados | nvarchar(MAX) | No | Campo de auditoría de fuente. |

### MuseosLatam_Datamart.aud.incidencia

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| tabla | varchar(40) | No | Campo de auditoría de incidencia. |
| source_row | bigint | No | Número de registro en el CSV de origen, desde 1. |
| regla | nvarchar(100) | No | Campo de auditoría de incidencia. |
| detalle | nvarchar(MAX) | No | Campo de auditoría de incidencia. |

### MuseosLatam_Datamart.aud.lote

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| fase | varchar(40) | No | Campo de auditoría de lote. |
| tabla | varchar(40) | No | Campo de auditoría de lote. |
| sha256 | char(64) | No | Campo de auditoría de lote. |
| inicio | bigint | No | Campo de auditoría de lote. |
| fin | bigint | No | Campo de auditoría de lote. |
| filas | bigint | No | Campo de auditoría de lote. |
| hash_lote | binary(32) | Sí | Campo de auditoría de lote. |
| confirmado | datetime2 | No | Campo de auditoría de lote. |

### MuseosLatam_Datamart.aud.propiedad

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| propietario | varchar(80) | No | Campo de auditoría de propiedad. |

### MuseosLatam_Datamart.aud.revision_semantica

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| version_revision | varchar(80) | No | Versión de la revisión semántica aplicada al catálogo de tópicos. |
| evidencia_sha256 | char(64) | No | Campo de auditoría de revision_semantica. |
| aplicado_utc | datetime2 | No | Campo de auditoría de revision_semantica. |
| revisor | nvarchar(200) | No | Campo de auditoría de revision_semantica. |
| validacion_humana | bit | No | Campo de auditoría de revision_semantica. |
| respaldo | nvarchar(MAX) | No | Campo de auditoría de revision_semantica. |

### MuseosLatam_Datamart.mart.dim_antiguedad_resena

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_antiguedad_resena | bigint | No | Clave sustituta. |
| nk_codigo | nvarchar(100) | No | Código natural del miembro de la dimensión. |
| etiqueta | nvarchar(200) | No | Etiqueta legible. |
| anios_min | int | Sí | Límite inferior de antigüedad de la reseña, en años. |
| anios_max | int | Sí | Límite superior; NULL en el tramo abierto. |

### MuseosLatam_Datamart.mart.dim_dimension_latente

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_dimension_latente | bigint | No | Clave sustituta. |
| nk_codigo | nvarchar(100) | No | Código natural del miembro de la dimensión. |
| version_modelo | nvarchar(100) | No | Versión del modelo de tópicos. |
| etiqueta | nvarchar(500) | No | Etiqueta legible. |
| descripcion | nvarchar(MAX) | No | Definición del tópico. |
| palabras_clave | nvarchar(MAX) | No | Términos más representativos del tópico. |
| metodo | nvarchar(100) | No | Método de modelado de tópicos (S-BERT + BERTopic). |
| validacion_etiqueta | nvarchar(100) | No | Resultado de la revisión semántica: soporte muestral o uso restringido. |
| criterios_inclusion | nvarchar(MAX) | Sí | Contenido que corresponde al tópico. |
| criterios_exclusion | nvarchar(MAX) | Sí | Contenido que no corresponde al tópico. |
| limitaciones | nvarchar(MAX) | Sí | Ambigüedades detectadas en la muestra revisada. |
| apto_analisis_tematico | bit | Sí | 1 si el tópico se usa en los indicadores temáticos (22 de 41). |
| muestra_revisada | int | Sí | Casos de la muestra revisados para el tópico. |
| soporte_muestral | decimal(6,4) | Sí | Proporción de casos de la muestra con soporte explícito de la etiqueta (C/n). |
| metodo_revision | nvarchar(500) | Sí | Procedimiento de la revisión semántica por muestreo. |

### MuseosLatam_Datamart.mart.dim_extension_resena

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_extension_resena | bigint | No | Clave sustituta. |
| nk_codigo | nvarchar(100) | No | Código natural del miembro de la dimensión. |
| etiqueta | nvarchar(200) | No | Etiqueta legible. |
| palabras_min | int | Sí | Límite inferior de palabras del tramo de extensión. |
| palabras_max | int | Sí | Límite superior; NULL en el tramo abierto. |

### MuseosLatam_Datamart.mart.dim_geografia

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_geografia | bigint | No | Clave sustituta. |
| nk_geografia | varchar(64) | No | Hash SHA-256 de país, niveles y código nativo (clave natural técnica). |
| codigo_pais | nvarchar(16) | No | Código ISO alfa-2 del país: PE, MX o AR. |
| pais_nombre | nvarchar(100) | No | Nombre del país. |
| nivel1_nombre | nvarchar(300) | No | Nombre de la división administrativa; NULL si el país no tiene ese nivel. |
| nivel1_tipo | nvarchar(50) | Sí | Tipo de división administrativa según el país. |
| nivel2_nombre | nvarchar(300) | No | Nombre de la división administrativa; NULL si el país no tiene ese nivel. |
| nivel2_tipo | nvarchar(50) | Sí | Tipo de división administrativa según el país. |
| nivel3_nombre | nvarchar(300) | Sí | Nombre de la división administrativa; NULL si el país no tiene ese nivel. |
| nivel3_tipo | nvarchar(50) | Sí | Tipo de división administrativa según el país. |
| codigo_nativo | nvarchar(100) | No | Código geográfico oficial (UBIGEO en Perú, geoBoundaries en México y Argentina). |
| sistema_codigo | nvarchar(50) | Sí | INEI_UBIGEO en PE; GEOBOUNDARIES_ADM2 en MX y AR. |

### MuseosLatam_Datamart.mart.dim_lugar

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_lugar | bigint | No | Clave sustituta. |
| clave_lugar | nvarchar(160) | No | País y Google Place ID unidos por dos puntos. |
| nk_place_id | nvarchar(140) | No | Google Place ID (distingue mayúsculas). |
| codigo_pais | nvarchar(16) | No | Código ISO alfa-2 del país: PE, MX o AR. |
| nombre | nvarchar(1000) | No | Nombre del museo o sitio en la ficha (puede repetirse). |
| categoria_normalizada | nvarchar(200) | No | Categoría analítica del lugar. |
| latitud | decimal(12,9) | Sí | Latitud decimal WGS84. |
| longitud | decimal(12,9) | Sí | Longitud decimal WGS84. |
| tiene_sitio_web | bit | No | 1 si la ficha declara dominio o URL. |
| tiene_telefono | bit | No | 1 si la ficha declara teléfono. |
| sk_geografia | bigint | No | Clave foránea a dim_geografia. |
| hash_atributos | binary(32) | No | Hash de los atributos de la ficha. |
| version_fuente | varchar(80) | No | Versión técnica del corpus cargado. |

### MuseosLatam_Datamart.mart.dim_perfil_autor

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_perfil_autor | bigint | No | Clave sustituta. |
| nk_codigo | nvarchar(100) | No | Código natural del miembro de la dimensión. |
| etiqueta | nvarchar(200) | No | Etiqueta legible. |
| resenas_min | int | Sí | Límite inferior de reseñas publicadas por el autor. |
| resenas_max | int | Sí | Límite superior; NULL en el tramo abierto. |

### MuseosLatam_Datamart.mart.dim_presencia_digital

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_presencia_digital | bigint | No | Clave sustituta. |
| nk_codigo | nvarchar(100) | No | Código natural del miembro de la dimensión. |
| etiqueta | nvarchar(200) | No | Etiqueta legible. |
| tiene_sitio_web | bit | Sí | 1 si la ficha declara dominio o URL. |
| tiene_telefono | bit | Sí | 1 si la ficha declara teléfono. |

### MuseosLatam_Datamart.mart.dim_rating

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_rating | bigint | No | Clave sustituta. |
| nk_codigo | nvarchar(100) | No | Código natural del miembro de la dimensión. |
| etiqueta | nvarchar(200) | No | Etiqueta legible. |
| nk_rating | smallint | Sí | Estrellas 1–5; NULL en el miembro desconocido. |

### MuseosLatam_Datamart.mart.dim_sentimiento

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_sentimiento | bigint | No | Clave sustituta. |
| nk_codigo | nvarchar(100) | No | Código natural del miembro de la dimensión. |
| etiqueta | nvarchar(200) | No | Etiqueta legible. |
| polaridad | smallint | Sí | -1 negativo, 0 neutro, 1 positivo; NULL si no hay clasificación. |
| es_texto_analizable | bit | Sí | 1 si la reseña tiene sentimiento negativo, neutro o positivo. |

### MuseosLatam_Datamart.mart.dim_tiempo

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_periodo | int | No | Clave primaria del período: AAAAMM, AAAA00 (año sin mes) o -1. |
| anio | smallint | Sí | Año estimado de la reseña; NULL si se desconoce. |
| mes | smallint | Sí | Mes 1–12; 0 si se desconoce el mes; NULL en el período -1. |
| anio_mes | char(7) | No | AAAA-MM, AAAA-00 si el mes se desconoce o 0000-00. |
| es_mes_determinado | bit | No | 1 si el mes de la reseña es conocido. |
| etapa | varchar(30) | No | PREPANDEMIA hasta 2019, PANDEMIA 2020–2021, POSPANDEMIA desde 2022, o desconocida. |

### MuseosLatam_Datamart.mart.fact_reputacion_lugar

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_reputacion | bigint | No | Clave sustituta. |
| sk_lugar | bigint | No | Clave foránea a dim_lugar. |
| sk_geografia | bigint | No | Clave foránea a dim_geografia. |
| sk_presencia_digital | bigint | No | Clave foránea a dim_presencia_digital. |
| rating_promedio_google | decimal(3,1) | Sí | Estrellas publicadas en la ficha de Google Maps. |
| n_valoraciones_google | bigint | Sí | Número de valoraciones publicado en la ficha. |
| source_row | bigint | No | Número de registro en el CSV de origen, desde 1. |

### MuseosLatam_Datamart.mart.fact_resena

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_resena | bigint | No | Clave sustituta. |
| nk_id_review | nvarchar(160) | No | Identificador de la reseña en Google Maps. |
| source_row | bigint | No | Número de registro en el CSV de origen, desde 1. |
| hash_fila | binary(32) | No | SHA-256 de los valores originales del registro. |
| codigo_pais | nvarchar(16) | No | Código ISO alfa-2 del país: PE, MX o AR. |
| sk_lugar | bigint | No | Clave foránea a dim_lugar. |
| sk_geografia | bigint | No | Clave foránea a dim_geografia. |
| sk_periodo | int | No | Clave foránea a dim_tiempo. |
| sk_perfil_autor | bigint | No | Clave foránea a dim_perfil_autor. |
| sk_rating | bigint | No | Clave foránea a dim_rating. |
| sk_sentimiento | bigint | No | Clave foránea a dim_sentimiento. |
| sk_extension_resena | bigint | No | Clave foránea a dim_extension_resena. |
| sk_antiguedad_resena | bigint | No | Clave foránea a dim_antiguedad_resena. |
| sk_presencia_digital | bigint | No | Clave foránea a dim_presencia_digital. |
| rating | smallint | Sí | Estrellas 1–5; NULL si la reseña no tiene calificación. Promedio = SUM(rating)/COUNT(rating). |
| cantidad_palabras | int | No | Número de palabras del texto; 0 sin texto. |
| n_resenas_autor_asof | int | Sí | Reseñas publicadas por el autor al extraer; NULL en 24 casos ambiguos. |
| puntaje_sentimiento | float | Sí | Puntaje del modelo de sentimiento en [-1, 1]. |
| tiene_texto | bit | No | 1 si la reseña tiene texto. |
| precision_fecha_resena | varchar(6) | No | Precisión de la fecha estimada: DIA, SEMANA, MES, ANIO o NA. |
| texto_resena | nvarchar(MAX) | No | Texto completo de la reseña. |
| estado_nlp | nvarchar(100) | No | Estado del análisis de sentimiento (OK, baja confianza, sin texto, etc.). |
| estado_topicos | nvarchar(100) | No | Estado de la asignación de tópico (asignado, outlier, fuera de alcance). |
| version_modelo_sentimiento | nvarchar(150) | No | Versión del modelo de sentimiento. |

### MuseosLatam_Datamart.mart.fact_resena_dimension

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| sk_resena | bigint | No | Clave foránea a fact_resena. |
| sk_dimension_latente | bigint | No | Clave foránea a dim_dimension_latente. |
| source_row | bigint | No | Número de registro en el CSV de origen, desde 1. |

## 2. MuseosLatam_Origen (base de origen de la carga)

### MuseosLatam_Origen.aud.ejecucion

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| id | bigint | No | Campo de auditoría de ejecucion. |
| inicio | datetime2 | No | Campo de auditoría de ejecucion. |
| fin | datetime2 | Sí | Campo de auditoría de ejecucion. |
| estado | varchar(40) | No | Campo de auditoría de ejecucion. |
| informe | nvarchar(MAX) | Sí | Campo de auditoría de ejecucion. |

### MuseosLatam_Origen.aud.fuente

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| tabla | varchar(40) | No | Campo de auditoría de fuente. |
| version | varchar(80) | No | Versión de la ficha observada. |
| sha256 | char(64) | No | Campo de auditoría de fuente. |
| filas | bigint | No | Campo de auditoría de fuente. |
| encabezados | nvarchar(MAX) | No | Campo de auditoría de fuente. |

### MuseosLatam_Origen.aud.incidencia

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| tabla | varchar(40) | No | Campo de auditoría de incidencia. |
| source_row | bigint | No | Número de registro en el CSV de origen, desde 1. |
| regla | nvarchar(100) | No | Campo de auditoría de incidencia. |
| detalle | nvarchar(MAX) | No | Campo de auditoría de incidencia. |

### MuseosLatam_Origen.aud.lote

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| fase | varchar(40) | No | Campo de auditoría de lote. |
| tabla | varchar(40) | No | Campo de auditoría de lote. |
| sha256 | char(64) | No | Campo de auditoría de lote. |
| inicio | bigint | No | Campo de auditoría de lote. |
| fin | bigint | No | Campo de auditoría de lote. |
| filas | bigint | No | Campo de auditoría de lote. |
| hash_lote | binary(32) | Sí | Campo de auditoría de lote. |
| confirmado | datetime2 | No | Campo de auditoría de lote. |

### MuseosLatam_Origen.aud.propiedad

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| propietario | varchar(80) | No | Campo de auditoría de propiedad. |

### MuseosLatam_Origen.curado.catalogo_topicos

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| version_revision | varchar(80) | No | Versión de la revisión semántica aplicada al catálogo de tópicos. |
| codigo_topico | nvarchar(100) | No | Campo técnico de catalogo_topicos. |
| version_modelo | nvarchar(100) | No | Versión del modelo de tópicos. |
| etiqueta | nvarchar(500) | No | Etiqueta legible. |
| descripcion | nvarchar(MAX) | No | Definición del tópico. |
| criterios_inclusion | nvarchar(MAX) | No | Contenido que corresponde al tópico. |
| criterios_exclusion | nvarchar(MAX) | No | Contenido que no corresponde al tópico. |
| limitaciones | nvarchar(MAX) | No | Ambigüedades detectadas en la muestra revisada. |
| palabras_clave | nvarchar(MAX) | No | Términos más representativos del tópico. |
| validacion_etiqueta | nvarchar(100) | No | Resultado de la revisión semántica: soporte muestral o uso restringido. |
| apto_analisis_tematico | bit | No | 1 si el tópico se usa en los indicadores temáticos (22 de 41). |
| muestra_n | int | No | Campo técnico de catalogo_topicos. |
| coherentes_n | int | No | Campo técnico de catalogo_topicos. |
| parciales_n | int | No | Campo técnico de catalogo_topicos. |
| no_coherentes_n | int | No | Campo técnico de catalogo_topicos. |
| soporte_muestral | decimal(6,4) | No | Proporción de casos de la muestra con soporte explícito de la etiqueta (C/n). |
| metodo_revision | nvarchar(500) | No | Procedimiento de la revisión semántica por muestreo. |
| detalle_paises | nvarchar(MAX) | No | Campo técnico de catalogo_topicos. |
| etiqueta_anterior | nvarchar(500) | No | Campo técnico de catalogo_topicos. |
| evidencia_sha256 | char(64) | No | Campo técnico de catalogo_topicos. |
| registrado_utc | datetime2 | No | Campo técnico de catalogo_topicos. |

### MuseosLatam_Origen.curado.evaluacion_sentimiento

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| version_revision | varchar(80) | No | Versión de la revisión semántica aplicada al catálogo de tópicos. |
| numero | int | No | Campo técnico de evaluacion_sentimiento. |
| id_review | nvarchar(160) | No | Campo técnico de evaluacion_sentimiento. |
| source_row | bigint | No | Número de registro en el CSV de origen, desde 1. |
| codigo_pais | nvarchar(16) | No | Código ISO alfa-2 del país: PE, MX o AR. |
| sentimiento_original | nvarchar(100) | No | Campo técnico de evaluacion_sentimiento. |
| estado_original | nvarchar(100) | No | Campo técnico de evaluacion_sentimiento. |
| sha256_texto | char(64) | No | Campo técnico de evaluacion_sentimiento. |
| juicio | char(1) | No | Campo técnico de evaluacion_sentimiento. |
| dictamen | nvarchar(300) | No | Campo técnico de evaluacion_sentimiento. |

### MuseosLatam_Origen.curado.evaluacion_topico

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| version_revision | varchar(80) | No | Versión de la revisión semántica aplicada al catálogo de tópicos. |
| codigo_topico | nvarchar(100) | No | Campo técnico de evaluacion_topico. |
| codigo_pais | nvarchar(16) | No | Código ISO alfa-2 del país: PE, MX o AR. |
| numero | int | No | Campo técnico de evaluacion_topico. |
| id_review | nvarchar(160) | No | Campo técnico de evaluacion_topico. |
| source_row | bigint | No | Número de registro en el CSV de origen, desde 1. |
| sha256_texto | char(64) | No | Campo técnico de evaluacion_topico. |
| juicio | char(1) | No | Campo técnico de evaluacion_topico. |
| criterio | nvarchar(250) | No | Campo técnico de evaluacion_topico. |

### MuseosLatam_Origen.stg.catalogo

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| source_row | bigint | No | Número de registro en el CSV de origen, desde 1. |
| hash_fila | binary(32) | No | SHA-256 de los valores originales del registro. |
| hash_fuente | char(64) | No | SHA-256 del archivo fuente. |
| codigo_topico | nvarchar(40) | No | Valor literal del CSV (ver mapa_campos.csv). |
| idioma | nvarchar(18) | No | Valor literal del CSV (ver mapa_campos.csv). |
| etiqueta | nvarchar(65) | No | Valor literal del CSV (ver mapa_campos.csv). |
| descripcion | nvarchar(171) | No | Valor literal del CSV (ver mapa_campos.csv). |
| palabras_clave | nvarchar(211) | No | Valor literal del CSV (ver mapa_campos.csv). |
| version_modelo | nvarchar(35) | No | Valor literal del CSV (ver mapa_campos.csv). |
| metodo | nvarchar(22) | No | Valor literal del CSV (ver mapa_campos.csv). |
| validacion_etiqueta | nvarchar(43) | No | Valor literal del CSV (ver mapa_campos.csv). |

### MuseosLatam_Origen.stg.lugar

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| source_row | bigint | No | Número de registro en el CSV de origen, desde 1. |
| hash_fila | binary(32) | No | SHA-256 de los valores originales del registro. |
| hash_fuente | char(64) | No | SHA-256 del archivo fuente. |
| codigo_pais | nvarchar(18) | No | Valor literal del CSV (ver mapa_campos.csv). |
| pais | nvarchar(25) | No | Valor literal del CSV (ver mapa_campos.csv). |
| pais_iso3 | nvarchar(19) | No | Valor literal del CSV (ver mapa_campos.csv). |
| clave_lugar | nvarchar(46) | No | Valor literal del CSV (ver mapa_campos.csv). |
| id | nvarchar(43) | No | Valor literal del CSV (ver mapa_campos.csv). |
| url_place | nvarchar(89) | No | Valor literal del CSV (ver mapa_campos.csv). |
| title | nvarchar(127) | No | Valor literal del CSV (ver mapa_campos.csv). |
| category | nvarchar(45) | No | Valor literal del CSV (ver mapa_campos.csv). |
| address | nvarchar(185) | No | Valor literal del CSV (ver mapa_campos.csv). |
| phoneNumber | nvarchar(40) | No | Valor literal del CSV (ver mapa_campos.csv). |
| completePhoneNumber | nvarchar(43) | No | Valor literal del CSV (ver mapa_campos.csv). |
| domain | nvarchar(66) | No | Valor literal del CSV (ver mapa_campos.csv). |
| url | nvarchar(552) | No | Valor literal del CSV (ver mapa_campos.csv). |
| coor | nvarchar(55) | No | Valor literal del CSV (ver mapa_campos.csv). |
| stars | nvarchar(19) | No | Valor literal del CSV (ver mapa_campos.csv). |
| reviews | nvarchar(24) | No | Valor literal del CSV (ver mapa_campos.csv). |
| source_query | nvarchar(118) | No | Valor literal del CSV (ver mapa_campos.csv). |
| query_text | nvarchar(118) | No | Valor literal del CSV (ver mapa_campos.csv). |
| nivel | nvarchar(28) | No | Valor literal del CSV (ver mapa_campos.csv). |
| palabra_clave | nvarchar(42) | No | Valor literal del CSV (ver mapa_campos.csv). |
| categoria_normalizada | nvarchar(39) | No | Valor literal del CSV (ver mapa_campos.csv). |
| prioridad | nvarchar(24) | No | Valor literal del CSV (ver mapa_campos.csv). |
| distrito | nvarchar(52) | No | Valor literal del CSV (ver mapa_campos.csv). |
| provincia | nvarchar(65) | No | Valor literal del CSV (ver mapa_campos.csv). |
| departamento | nvarchar(47) | No | Valor literal del CSV (ver mapa_campos.csv). |
| inei | nvarchar(24) | No | Valor literal del CSV (ver mapa_campos.csv). |
| lat | nvarchar(35) | No | Valor literal del CSV (ver mapa_campos.csv). |
| lon | nvarchar(34) | No | Valor literal del CSV (ver mapa_campos.csv). |
| inei_real | nvarchar(39) | No | Valor literal del CSV (ver mapa_campos.csv). |
| distrito_real | nvarchar(52) | No | Valor literal del CSV (ver mapa_campos.csv). |
| provincia_real | nvarchar(65) | No | Valor literal del CSV (ver mapa_campos.csv). |
| departamento_real | nvarchar(47) | No | Valor literal del CSV (ver mapa_campos.csv). |
| distrito_no_encontrado_en_poligonos | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| coincide_con_distrito_de_consulta | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| distrito_final | nvarchar(52) | No | Valor literal del CSV (ver mapa_campos.csv). |
| provincia_final | nvarchar(65) | No | Valor literal del CSV (ver mapa_campos.csv). |
| departamento_final | nvarchar(47) | No | Valor literal del CSV (ver mapa_campos.csv). |
| coincide_keyword_en_nombre | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| categoria_google_es_ruido_conocido | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| categoria_google_es_buena_senal | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| categoria_google_es_ruido_genuino | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| confianza_clasificacion | nvarchar(25) | No | Valor literal del CSV (ver mapa_campos.csv). |
| motivo_descarte | nvarchar(46) | No | Valor literal del CSV (ver mapa_campos.csv). |
| banderas_calidad | nvarchar(18) | No | Valor literal del CSV (ver mapa_campos.csv). |
| archivo_origen | nvarchar(54) | No | Valor literal del CSV (ver mapa_campos.csv). |
| registro_origen | nvarchar(20) | No | Valor literal del CSV (ver mapa_campos.csv). |
| fecha_observacion_reputacion | nvarchar(16) | No | Valor literal del CSV (ver mapa_campos.csv). |
| precision_observacion_reputacion | nvarchar(30) | No | Valor literal del CSV (ver mapa_campos.csv). |

### MuseosLatam_Origen.stg.puente

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| source_row | bigint | No | Número de registro en el CSV de origen, desde 1. |
| hash_fila | binary(32) | No | SHA-256 de los valores originales del registro. |
| hash_fuente | char(64) | No | SHA-256 del archivo fuente. |
| id_review | nvarchar(84) | No | Valor literal del CSV (ver mapa_campos.csv). |
| codigo_topico | nvarchar(40) | No | Valor literal del CSV (ver mapa_campos.csv). |
| peso | nvarchar(17) | No | Valor literal del CSV (ver mapa_campos.csv). |
| es_dominante | nvarchar(17) | No | Valor literal del CSV (ver mapa_campos.csv). |
| version_modelo | nvarchar(35) | No | Valor literal del CSV (ver mapa_campos.csv). |

### MuseosLatam_Origen.stg.resena

| Campo | Tipo | NULL | Descripción |
|---|---|---|---|
| source_row | bigint | No | Número de registro en el CSV de origen, desde 1. |
| hash_fila | binary(32) | No | SHA-256 de los valores originales del registro. |
| hash_fuente | char(64) | No | SHA-256 del archivo fuente. |
| google_place_id | nvarchar(43) | No | Valor literal del CSV (ver mapa_campos.csv). |
| nombre_lugar | nvarchar(127) | No | Valor literal del CSV (ver mapa_campos.csv). |
| categoria_google | nvarchar(45) | No | Valor literal del CSV (ver mapa_campos.csv). |
| distrito | nvarchar(52) | No | Valor literal del CSV (ver mapa_campos.csv). |
| provincia | nvarchar(65) | No | Valor literal del CSV (ver mapa_campos.csv). |
| departamento | nvarchar(47) | No | Valor literal del CSV (ver mapa_campos.csv). |
| id_review | nvarchar(84) | No | Valor literal del CSV (ver mapa_campos.csv). |
| caption | nvarchar(MAX) | No | Valor literal del CSV (ver mapa_campos.csv). |
| relative_date | nvarchar(49) | No | Valor literal del CSV (ver mapa_campos.csv). |
| review_date | nvarchar(42) | No | Valor literal del CSV (ver mapa_campos.csv). |
| retrieval_date | nvarchar(42) | No | Valor literal del CSV (ver mapa_campos.csv). |
| rating | nvarchar(19) | No | Valor literal del CSV (ver mapa_campos.csv). |
| username | nvarchar(99) | No | Valor literal del CSV (ver mapa_campos.csv). |
| n_review_user | nvarchar(22) | No | Valor literal del CSV (ver mapa_campos.csv). |
| url_user | nvarchar(173) | No | Valor literal del CSV (ver mapa_campos.csv). |
| url_source | nvarchar(89) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_id | nvarchar(43) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_url_place | nvarchar(89) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_title | nvarchar(127) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_category | nvarchar(45) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_address | nvarchar(185) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_phoneNumber | nvarchar(40) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_completePhoneNumber | nvarchar(43) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_domain | nvarchar(66) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_url | nvarchar(258) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_coor | nvarchar(55) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_stars | nvarchar(19) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_reviews | nvarchar(24) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_source_query | nvarchar(118) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_query_text | nvarchar(118) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_nivel | nvarchar(28) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_palabra_clave | nvarchar(42) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_categoria_normalizada | nvarchar(39) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_prioridad | nvarchar(24) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_distrito | nvarchar(52) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_provincia | nvarchar(65) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_departamento | nvarchar(47) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_inei | nvarchar(24) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_lat | nvarchar(35) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_lon | nvarchar(34) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_inei_real | nvarchar(39) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_distrito_real | nvarchar(52) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_provincia_real | nvarchar(65) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_departamento_real | nvarchar(47) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_distrito_no_encontrado_en_poligonos | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_coincide_con_distrito_de_consulta | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_distrito_final | nvarchar(52) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_provincia_final | nvarchar(65) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_departamento_final | nvarchar(47) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_coincide_keyword_en_nombre | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_categoria_google_es_ruido_conocido | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_categoria_google_es_buena_senal | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_categoria_google_es_ruido_genuino | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_confianza_clasificacion | nvarchar(25) | No | Valor literal del CSV (ver mapa_campos.csv). |
| museo_motivo_descarte | nvarchar(46) | No | Valor literal del CSV (ver mapa_campos.csv). |
| cantidad_palabras | nvarchar(19) | No | Valor literal del CSV (ver mapa_campos.csv). |
| tiene_texto | nvarchar(17) | No | Valor literal del CSV (ver mapa_campos.csv). |
| n_resenas_autor_asof | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| segmento_perfil_autor | nvarchar(29) | No | Valor literal del CSV (ver mapa_campos.csv). |
| segmento_extension | nvarchar(25) | No | Valor literal del CSV (ver mapa_campos.csv). |
| fecha_estimada_analitica | nvarchar(41) | No | Valor literal del CSV (ver mapa_campos.csv). |
| precision_fecha_resena | nvarchar(22) | No | Valor literal del CSV (ver mapa_campos.csv). |
| periodo_codigo | nvarchar(22) | No | Valor literal del CSV (ver mapa_campos.csv). |
| segmento_antiguedad | nvarchar(30) | No | Valor literal del CSV (ver mapa_campos.csv). |
| segmento_presencia_digital | nvarchar(29) | No | Valor literal del CSV (ver mapa_campos.csv). |
| codigo_pais | nvarchar(18) | No | Valor literal del CSV (ver mapa_campos.csv). |
| pais | nvarchar(25) | No | Valor literal del CSV (ver mapa_campos.csv). |
| pais_iso3 | nvarchar(19) | No | Valor literal del CSV (ver mapa_campos.csv). |
| clave_lugar | nvarchar(46) | No | Valor literal del CSV (ver mapa_campos.csv). |
| corrida_fuente | nvarchar(19) | No | Valor literal del CSV (ver mapa_campos.csv). |
| registro_completo_fuente | nvarchar(21) | No | Valor literal del CSV (ver mapa_campos.csv). |
| pais_fuente | nvarchar(18) | No | Valor literal del CSV (ver mapa_campos.csv). |
| banderas_calidad | nvarchar(60) | No | Valor literal del CSV (ver mapa_campos.csv). |
| categoria_museo_incluida | nvarchar(17) | No | Valor literal del CSV (ver mapa_campos.csv). |
| categoria_museo_exacta | nvarchar(17) | No | Valor literal del CSV (ver mapa_campos.csv). |
| hash_texto_nlp | nvarchar(80) | No | Valor literal del CSV (ver mapa_campos.csv). |
| codigo_idioma | nvarchar(18) | No | Valor literal del CSV (ver mapa_campos.csv). |
| confianza_idioma | nvarchar(36) | No | Valor literal del CSV (ver mapa_campos.csv). |
| metodo_idioma | nvarchar(22) | No | Valor literal del CSV (ver mapa_campos.csv). |
| sentimiento | nvarchar(30) | No | Valor literal del CSV (ver mapa_campos.csv). |
| puntaje_sentimiento | nvarchar(39) | No | Valor literal del CSV (ver mapa_campos.csv). |
| confianza_sentimiento | nvarchar(35) | No | Valor literal del CSV (ver mapa_campos.csv). |
| p_negativo | nvarchar(37) | No | Valor literal del CSV (ver mapa_campos.csv). |
| p_neutro | nvarchar(36) | No | Valor literal del CSV (ver mapa_campos.csv). |
| p_positivo | nvarchar(37) | No | Valor literal del CSV (ver mapa_campos.csv). |
| version_modelo_sentimiento | nvarchar(67) | No | Valor literal del CSV (ver mapa_campos.csv). |
| numero_tokens | nvarchar(20) | No | Valor literal del CSV (ver mapa_campos.csv). |
| ventanas_texto | nvarchar(17) | No | Valor literal del CSV (ver mapa_campos.csv). |
| estado_nlp | nvarchar(35) | No | Valor literal del CSV (ver mapa_campos.csv). |
| estado_topicos | nvarchar(36) | No | Valor literal del CSV (ver mapa_campos.csv). |
| topico_dominante | nvarchar(40) | No | Valor literal del CSV (ver mapa_campos.csv). |
| version_modelo_topicos | nvarchar(35) | No | Valor literal del CSV (ver mapa_campos.csv). |
| asignacion_topico_es_probabilidad | nvarchar(17) | No | Valor literal del CSV (ver mapa_campos.csv). |
| archivo_origen | nvarchar(75) | No | Valor literal del CSV (ver mapa_campos.csv). |
| registro_origen | nvarchar(22) | No | Valor literal del CSV (ver mapa_campos.csv). |
