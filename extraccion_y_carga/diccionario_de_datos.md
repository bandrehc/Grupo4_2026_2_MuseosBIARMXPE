# Diccionario de datos de las fuentes extraídas

Variables tal como se obtuvieron en la extracción (archivos de `data/`). El diccionario del datamart final
(dimensiones, hechos y medidas) está en [`../docs/diccionario_analitico.md`](../docs/diccionario_analitico.md) y el
diccionario físico de las bases SQL Server en
[`carga_sql_server/DICCIONARIO_SQL_SERVER.md`](carga_sql_server/DICCIONARIO_SQL_SERVER.md). La trazabilidad
de cada campo fuente a su destino está en [`carga_sql_server/mapa_campos.csv`](carga_sql_server/mapa_campos.csv).

Los campos propios del proceso de extracción (estado del scraper, conteos del panel, fecha de extracción e
identidad pública del autor) se documentan aquí, pero no forman parte del modelo analítico.

Las variables provienen de tres grupos de archivos: la tabla de reseñas, la base de museos y la tabla de cobertura de extracción.

### A.1 Tabla de reseñas

Grano: una fila por reseña única, identificada por `(google_place_id, id_review)`.

*Tabla 1. Variables de la tabla de reseñas.*

| Variable | Tipo | Unidad | Descripción |
|---|---|---|---|
| `pais` | Texto | N/A | País de extracción. Solo en el consolidado (`comentarios_museos_consolidado`). |
| `codigo_pais` | Texto (2) | N/A | Código ISO 3166-1 alfa-2 (`PE`, `MX`, `AR`). Solo en el corpus final con NLP. |
| `google_place_id` | Texto | N/A | Identificador de Google Maps del museo (inicia con `ChIJ`). Clave natural del lugar. |
| `nombre_lugar` | Texto | N/A | Nombre de la ficha del museo. No es único. |
| `categoria_google` | Texto | N/A | Categoría de la ficha en Google (por ejemplo, `Museo`, `Sitio histórico`). |
| `distrito` | Texto | N/A | Distrito del lugar (Perú). Vacío en México y Argentina. |
| `provincia` | Texto | N/A | Provincia (Perú), municipio o alcaldía (México) o departamento/partido (Argentina). |
| `departamento` | Texto | N/A | Departamento (Perú), entidad federativa (México) o provincia (Argentina). |
| `id_review` | Texto (31 a 68) | N/A | Identificador opaco de la reseña asignado por Google. Único junto con `google_place_id`. |
| `caption` | Texto | Caracteres | Texto de la reseña. Vacío si el autor solo calificó. En Perú, la media es 105 caracteres y el máximo 3 877. |
| `relative_date` | Texto | Tiempo relativo | Antigüedad publicada por Google (por ejemplo, "Hace 6 meses", "Hace un año"). Es el único dato temporal original. |
| `review_date` | Fecha y hora | Fecha y hora | Fecha estimada de publicación: `retrieval_date` menos `relative_date`. Precisión de día a año. |
| `retrieval_date` | Fecha y hora | Fecha y hora | Momento real de extracción de la reseña. |
| `rating` | Entero (1 a 5) | Estrellas | Calificación otorgada. Se guarda como `1.0` a `5.0`. |
| `username` | Texto | N/A | Nombre público del autor. Puede repetirse, no identifica. |
| `n_review_user` | Entero | Reseñas | Cantidad de reseñas públicas del autor al momento de la extracción. |
| `url_user` | URL | N/A | Enlace al perfil público del autor. Contiene su identificador numérico de contribuidor. |
| `url_source` | URL | N/A | Enlace a la ficha del museo en Google Maps. |

### A.2 Base de museos

Grano: un museo por fila.

*Tabla 2. Variables de la base de museos.*

| Variable | Tipo | Unidad | Descripción |
|---|---|---|---|
| `id` | Texto | N/A | Google Place ID. Clave del museo. |
| `url_place` | URL | N/A | Enlace a la ficha en Google Maps. |
| `title` | Texto | N/A | Nombre del lugar. Hay títulos repetidos. |
| `category` | Texto | N/A | Categoría de Google. En México es `Museo` por el filtro de inclusión; en Perú y Argentina incluye subcategorías patrimoniales. |
| `address` | Texto | N/A | Dirección en texto libre. |
| `phoneNumber` | Texto | N/A | Teléfono en formato local. |
| `completePhoneNumber` | Texto | N/A | Teléfono con prefijo internacional. |
| `domain` | Texto | N/A | Dominio del sitio web declarado (puede ser una red social). |
| `url` | URL | N/A | Sitio web declarado. |
| `coor` | Texto | Grados | Par `latitud,longitud` original de la búsqueda. |
| `stars` | Decimal (1.0 a 5.0) | Estrellas | Promedio de calificaciones mostrado por Google. Métrica móvil (instantánea). |
| `reviews` | Entero | Reseñas | Conteo de reseñas del listado de búsqueda. Métrica móvil y no equivale al techo de extracción. |
| `source_query` | Texto | N/A | Consulta que originó el hallazgo. |
| `query_text` | Texto | N/A | Texto de la consulta ejecutada. |
| `nivel` | Texto | N/A | Nivel de granularidad de la consulta (`distrito`, `provincia`, `departamento`). |
| `palabra_clave` | Texto | N/A | Término de la taxonomía usado en la consulta (por ejemplo, `museo de sitio`). |
| `categoria_normalizada` | Texto | N/A | Categoría de la taxonomía propia: `museo`, `sitio_arqueologico`, `sitio_interes_historico`, `patrimonio_religioso`. |
| `prioridad` | Texto | N/A | Prioridad de la palabra clave (`alta`, `opcional`). |
| `distrito`, `provincia`, `departamento` | Texto | N/A | Geografía de la consulta que originó el hallazgo (no necesariamente la real). |
| `inei` | Numérico | N/A | Código de la unidad geográfica de la consulta. En Perú es el UBIGEO; en México solo toma 2 valores y carece de valor analítico. |
| `lat` | Decimal | Grados decimales (WGS84) | Latitud del lugar. |
| `lon` | Decimal | Grados decimales (WGS84) | Longitud del lugar. |
| `inei_real` | Texto | N/A | Código de la unidad que contiene el punto: UBIGEO de 6 dígitos (Perú) o identificador geoBoundaries (México). |
| `distrito_real`, `provincia_real`, `departamento_real` | Texto | N/A | Geografía asignada por las coordenadas (cruce espacial). |
| `distrito_no_encontrado_en_poligonos` | Booleano | N/A | Verdadero si el punto no cayó en un polígono distrital y se usó la geografía de la consulta como respaldo. |
| `coincide_con_distrito_de_consulta` | Booleano | N/A | Verdadero si la geografía real coincide con la de la consulta. |
| `distrito_final`, `provincia_final`, `departamento_final` | Texto | N/A | Geografía definitiva del museo, en formato de título. Es la que se usa en el análisis. `distrito_final` está vacío en México. |
| `coincide_keyword_en_nombre` | Booleano | N/A | Verdadero si el nombre contiene una raíz de palabra clave de la taxonomía. |
| `categoria_google_es_ruido_conocido` | Booleano | N/A | Verdadero si la categoría de Google pertenece a la lista de ruido conocido. |
| `categoria_google_es_buena_senal` | Booleano | N/A | Verdadero si la categoría de Google es señal positiva de patrimonio. |
| `categoria_google_es_ruido_genuino` | Booleano | N/A | Verdadero si la categoría corresponde a ruido genuino (excluido en la etapa 3 salvo señal positiva). |
| `confianza_clasificacion` | Texto | N/A | Confianza de la clasificación (`alta`, `baja`). Es `alta` en todos los museos y por tanto no discrimina. |

### A.3 Cobertura de extracción por museo

Grano: un museo por fila.

*Tabla 3. Variables de la tabla de cobertura.*

| Variable | Tipo | Unidad | Descripción |
|---|---|---|---|
| `lugar_id` | Texto | N/A | Google Place ID del museo. |
| `url_place` | URL | N/A | Enlace a la ficha. |
| `nombre` | Texto | N/A | Nombre del museo. |
| `categoria_google` | Texto | N/A | Categoría de Google. |
| `distrito`, `provincia`, `departamento` | Texto | N/A | Geografía registrada en el estado de extracción. |
| `n_reviews_google` | Entero | Reseñas | Conteo del listado de búsqueda (`reviews`). No es denominador de cobertura. |
| `status` | Texto | N/A | Estado: `completado`, `fallido`, `pendiente`, `en_progreso`. |
| `attempts` | Entero | Intentos | Intentos realizados. |
| `last_error` | Texto | N/A | Último error registrado (por ejemplo, `sort_by_failed`). |
| `n_reviews_obtenidas` | Entero | Reseñas | Reseñas contadas por el estado de extracción. |
| `started_at`, `completed_at` | Fecha y hora | UTC (ISO 8601) | Inicio y fin del procesamiento del museo. |
| `n_reviews_obtenidas_real` | Entero | Reseñas | Reseñas realmente presentes en el archivo consolidado. |
| `techo_alcanzado` | Booleano | N/A | Verdadero si se alcanzó el tope de reseñas por lugar. |
| `brecha_vs_conteo_busqueda` | Entero | Reseñas | Diferencia entre el conteo de búsqueda y lo extraído. No representa reseñas perdidas. |
| `sospechoso_cero_resenas` | Booleano | N/A | Verdadero si el museo figura completado con cero reseñas y con reseñas reportadas. |
