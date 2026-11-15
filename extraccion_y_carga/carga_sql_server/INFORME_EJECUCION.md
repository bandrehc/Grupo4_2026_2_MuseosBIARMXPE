# Informe de ejecución de la carga ETL a SQL Server

**Resultado: ejecutado y verificado.** Motor SQL Server 2019 Developer (64 bits, `15.0.2200.2`), Python 3.12,
pyodbc 5.3.0 y Microsoft ODBC Driver 17. No se utilizó SSIS: la carga es Python + T-SQL.

Bases creadas: **MuseosLatam_Origen** (`stg`, `curado`, `aud`) y **MuseosLatam_Datamart** (`mart`, `aud`).
Ambas usan la colación `Latin1_General_100_BIN2`, recuperación SIMPLE y restricciones habilitadas.
Los seis CSV de entrada se verificaron contra sus SHA-256 antes de la carga
([manifiesto](../docs/controles_corpus/validacion_final.json)).

## Filas cargadas y conciliadas

| Tabla origen | Esperadas | Cargadas |
|---|---:|---:|
| stg.resena | 1.143.877 | 1.143.877 |
| stg.lugar | 6.538 | 6.538 |
| stg.catalogo | 41 | 41 |
| stg.puente | 233.556 | 233.556 |

| Hecho destino | Esperadas | Cargadas |
|---|---:|---:|
| mart.fact_resena | 1.143.877 | 1.143.877 |
| mart.fact_resena_dimension | 233.556 | 233.556 |
| mart.fact_reputacion_lugar | 6.286 | 6.286 |

| País | Reseñas | Ratings NULL | Con texto | Suma rating |
|---|---:|---:|---:|---:|
| AR | 461.594 | 710 | 292.344 | 2.077.740 |
| MX | 560.328 | 0 | 270.051 | 2.569.857 |
| PE | 121.955 | 235 | 60.943 | 545.814 |

Se conservaron las **520.539 reseñas sin texto**, los **945 ratings NULL**, los 24 historiales de autor
ambiguos y las 14 banderas de carácter Unicode de reemplazo. Ninguna fila se rechazó ni se descartó.

Reputación: 2.081 AR + 2.701 MX + 1.504 PE = **6.286** observaciones. Las 252 fichas sin métricas publicadas
permanecen en `dim_lugar` sin hecho de reputación; la fuente no informa la fecha de observación
(período -1, precisión `NO_DOCUMENTADA`).

## Piloto e idempotencia

El piloto cargó 12 reseñas estratificadas de PE/MX/AR, los 6.538 lugares y los 41 tópicos, cubriendo reseñas
con y sin texto, rating ausente, todas las precisiones de fecha, autor ambiguo, Unicode, comas, comillas y
texto de longitud máxima. Se ejecutó dos veces sin duplicar filas.

Carga completa: 968,5 s. Segunda ejecución completa como proceso independiente: 370,7 s, sin volver a insertar
lotes ya aplicados.

| Tabla destino | Tras la carga | Tras la segunda ejecución | Delta |
|---|---:|---:|---:|
| dim_antiguedad_resena | 5 | 5 | 0 |
| dim_dimension_latente | 42 | 42 | 0 |
| dim_extension_resena | 6 | 6 | 0 |
| dim_geografia | 2.197 | 2.197 | 0 |
| dim_idioma | 32 | 32 | 0 |
| dim_lugar | 6.539 | 6.539 | 0 |
| dim_perfil_autor | 5 | 5 | 0 |
| dim_presencia_digital | 5 | 5 | 0 |
| dim_rating | 6 | 6 | 0 |
| dim_sentimiento | 5 | 5 | 0 |
| dim_tiempo | 365 | 365 | 0 |
| fact_reputacion_lugar | 6.286 | 6.286 | 0 |
| fact_resena | 1.143.877 | 1.143.877 | 0 |
| fact_resena_dimension | 233.556 | 233.556 | 0 |

Cada ejecución queda registrada en `MuseosLatam_Datamart.aud.ejecucion`; `00_ver_resultados.sql` consulta
los conteos antes y después. La dimensión `dim_idioma` se retiró después en la depuración del datamart
(ver [`../../datamart/README.md`](../../datamart/README.md)), por lo que el modelo final tiene 10 dimensiones.

## Pruebas ejecutadas

| Prueba | Resultado |
|---|---|
| Anti-joins de reseñas, lugares, catálogo y puente (faltantes y sobrantes) | OK (0 diferencias) |
| Reseñas duplicadas | OK (0) |
| Geografía inconsistente; período, mes o trimestre asignado sin dato de origen | OK (0) |
| Coordenadas fuera de rango; fecha de reputación asignada sin dato de origen | OK (0) |
| Peso distinto de 1 en el puente; texto con hash o longitud diferente | OK (0) |
| Presencia digital inconsistente; historial de autor asignado a casos ambiguos | OK (0) |
| Restricciones no confiables; miembros desconocidos en todas las dimensiones; FK y CHECK reales | OK |
| Campos del hecho y medidas de reputación frente a la fuente | OK (0 diferencias) |
| Cobertura y 123 distribuciones país × tópico | OK |
| SHA-256 por registro de todos los campos CSV ↔ SQL | OK en las cuatro fuentes |
| Unicode, vacíos, texto largo y multilínea (tablas temporales) | OK, lectura exacta |
| Claves que difieren solo en mayúsculas (tablas temporales) | Ambas conservadas |
| Rollback y commit conjunto de filas y checkpoint | OK |
| Exclusión de un segundo cargador concurrente (`sp_getapplock`) | Rechazado correctamente |
| Misma carga completa ejecutada de nuevo | Delta 0 en las 14 tablas |

La lectura de vuelta recalculó el SHA-256 de cada registro con los valores devueltos por SQL y lo comparó con
un nuevo parseo del CSV; no se limitó a comparar conteos. Longitud máxima de texto preservada: 4.093 unidades
UTF-16. `DBCC CHECKCONSTRAINTS` verificó FK y CHECK sobre las tablas cargadas; ninguna restricción se deshabilitó.

## Tamaño de las bases

| Base | Datos | Log |
|---|---:|---:|
| MuseosLatam_Origen | 4.744 MB | 648 MB |
| MuseosLatam_Datamart | 968 MB | 264 MB |

El cargador trabaja por lotes, sin cargar el corpus completo en memoria.

## Evidencia

`evidencia_carga_inicial.json`, `evidencia_final.json`, `evidencia_piloto.json`, `evidencia_complementaria.json`,
`pruebas_driver.json` y `prueba_exclusion.json` contienen los resultados en formato de máquina. La revisión
semántica de tópicos aplicada después de la carga está en [`revision_ia_v1/`](revision_ia_v1/README.md).
