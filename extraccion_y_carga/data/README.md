# Fuentes extraídas

Datos obtenidos de fichas y reseñas públicas de Google Maps para Perú, México y Argentina. Variables descritas
en el [diccionario de datos](../diccionario_de_datos.md).

| Carpeta / archivo | Contenido |
|---|---|
| `referencia/` | Configuración de países (`paises_latam.csv`, ver [README](referencia/README_configuracion_paises.md)), taxonomía de categorías, consultas de búsqueda y geografía (UBIGEO de Perú, divisiones de México y Argentina, límites nacionales GeoJSON) |
| `lugares/base_museos_peru.csv`, `base_museos_mexico.csv`, `base_museos_argentina.csv` | Universo de lugares por país, con claves, geografía y métricas de la ficha |
| `lugares/lugares_identificados*`, `lugares_descartados*`, `lugares_candidatos_argentina*` | Resultado de la depuración: lugares aceptados y descartados con su motivo |
| `resenas/paquetes/comentarios_museos_consolidado.csv.gz` | Consolidado de reseñas de Perú y Argentina (583.549 reseñas), con `pais`, `corrida` y `registro_completo` |
| `resenas/paquetes/comentarios_museos_crudo_argentina.csv.gz` | Extracción cruda de Argentina |
| `resenas/comentarios_museos_crudo.csv`, `resenas_museos_consolidadas.csv` (y `.parquet` por departamento) | Extracción de la primera corrida de Perú |
| `resenas/_consolidado_procedencia.csv` | Procedencia de cada reseña del consolidado (corrida de extracción de origen) |
| `resenas/cobertura_museos_por_lugar*.csv` | Cobertura de extracción por lugar: estado, intentos, último error y reseñas obtenidas |

Los paquetes `.csv.gz` se generan con `repos_wrapper/empaquetar_resenas.py` para respetar el límite de 100 MB por
archivo de GitHub. El consolidado completo de México y el corpus final con NLP (1.143.877 reseñas, seis CSV
verificables con [`validacion_final.json`](../docs/controles_corpus/validacion_final.json)) superan ese límite; su
contenido íntegro está cargado en el respaldo del datamart enlazado desde el [README principal](../../README.md).

Se preservan ratings ausentes, historiales de autor ambiguos, caracteres Unicode y reseñas sin texto. Las fichas no
constituyen un censo oficial de museos y las reseñas no son una muestra representativa de visitantes.
