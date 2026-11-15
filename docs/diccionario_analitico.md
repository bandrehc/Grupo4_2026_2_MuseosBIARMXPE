# Diccionario analítico y contrato de consumo

El [diagrama relacional](img/modelo_relacional_mart.svg) contiene los nombres, tipos, nulabilidad y PK/FK
de cada tabla del datamart, y el [diccionario físico](../extraccion_y_carga/carga_sql_server/DICCIONARIO_SQL_SERVER.md)
describe cada columna. Este documento añade el significado de negocio de cada dimensión, hecho y medida.
El diagrama se regenera desde la base con `scripts/generar_diagramas.py`.

## Dimensiones

| Dimensión | Clave de acceso | Significado y atributos de negocio |
|---|---|---|
| `dim_lugar` | `sk_lugar`, `nk_place_id` | Ficha de la institución: nombre, categoría, latitud/longitud y FK geográfica. |
| `dim_geografia` | `sk_geografia`, `nk_geografia` | País, niveles administrativos 1–3 y código territorial oficial. Se agrupa por clave, porque hay nombres repetidos. |
| `dim_tiempo` | `sk_periodo` | Año, mes cuando se conoce, precisión de la fecha y etapa (prepandemia, pandemia, pospandemia). El período AAAA00 representa un año sin mes; -1 es desconocido. |
| `dim_rating` | `sk_rating` | Nivel de estrellas 1–5; el miembro desconocido corresponde a reseñas sin calificación. |
| `dim_sentimiento` | `sk_sentimiento` | Sentimiento del texto calculado por el modelo (negativo, neutro, positivo, sin texto, no clasificado), independiente de las estrellas. |
| `dim_perfil_autor` | `sk_perfil_autor` | Tramo del número de reseñas públicas del autor. |
| `dim_extension_resena` | `sk_extension_resena` | Tramo de longitud del texto en palabras. |
| `dim_antiguedad_resena` | `sk_antiguedad_resena` | Tramo de antigüedad de la reseña respecto de la extracción. |
| `dim_presencia_digital` | `sk_presencia_digital` | Combinación de sitio web y teléfono declarados en la ficha. |
| `dim_dimension_latente` | `sk_dimension_latente`, `nk_codigo` | Tópico del modelo (41 + desconocido): etiqueta, definición, criterios, resultado de la revisión por muestreo y bandera `apto_analisis_tematico`. |

El miembro -1 conserva las reseñas cuya dimensión se desconoce; no se cuenta como institución.
La dimensión idioma se retiró en la depuración porque el detector era poco fiable en textos cortos; el
idioma detectado se conserva en la base de origen.

## Hechos

| Hecho | Grano | Medidas y reglas de uso |
|---|---|---|
| `fact_resena` | Una reseña (`nk_id_review`) | `rating` (admite NULL), cantidad de palabras, texto, banderas y puntaje de sentimiento. 1.143.877 filas. |
| `fact_resena_dimension` | Reseña × tópico | Puente de 233.556 pertenencias. El modelo asigna un tópico dominante por reseña y el esquema admite N:M; al unir el puente no se multiplican medidas de la reseña. |
| `fact_reputacion_lugar` | Ficha con métricas publicadas | Rating y número de valoraciones que muestra la ficha de Google (6.286 fichas). Son cifras de la ficha completa, distintas de las reseñas extraídas, y no tienen fecha de observación. |

## Contrato de medidas de la capa BI

| Indicador | Numerador / denominador | Regla |
|---|---|---|
| Reseñas | SUM(n_resenas) | Filtrado por país, categoría efectiva y años; las reseñas sin año quedan fuera de un rango de años. |
| Rating | SUM(suma_rating) / SUM(n_ratings) | El denominador excluye las reseñas sin rating; nunca se promedian promedios. |
| Rating bajo | SUM(n_rating_neg) / SUM(n_ratings) | Reseñas de 1–2 estrellas; es distinto del sentimiento negativo. |
| Sentimiento negativo | SUM(n_neg) / SUM(n_pos+n_neu+n_neg) | Denominador: solo reseñas clasificadas. Si es cero, se muestra n/d. |
| Con texto | SUM(n_con_texto) / SUM(n_resenas) | Proporción de reseñas con texto. |
| Cobertura temática habilitada | SUM(menciones habilitadas) / SUM(reseñas con texto) | Equivale a cobertura de reseñas porque cada reseña tiene como máximo un tópico. |
| Rating suavizado | (suma_rating + 20 × media del grupo) / (n_ratings + 20) | Grupo país × categoría en el período elegido; el prior de 20 es una decisión de diseño. |
| Percentil | PERCENT_RANK del rating suavizado entre pares | Solo lugares con ≥30 ratings en el período; los empates comparten posición y un único comparable da 0. |

`bi.agg_lugar_anio`: lugar × año, con conteos y sumas. `bi.agg_lugar_topico_anio`: lugar × año × tópico
habilitado. `bi.agg_topico_sent_anio`: país × categoría × año × tópico × sentimiento. `bi.lugar` usa la
categoría efectiva de la curaduría y conserva la original. El usuario de solo lectura del dashboard no
accede a las tablas de decisiones. Los textos individuales pueden contener datos personales, por eso el
dashboard no muestra autores.
