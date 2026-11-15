# `repos_wrapper/` — scripts propios del pipeline

Todos los scripts resuelven rutas con `PROJECT_ROOT = parent.parent`, así que **no se mueven de carpeta**. Se ejecutan desde la raíz del repositorio (`python3 repos_wrapper/<script>.py`). Los repositorios base de scraping están en [`../repos/`](../repos/).

## Procesamiento NLP y corpus final

- [fases12/](fases12/): preparación de textos, idioma (Lingua) y sentimiento (Cardiff XLM-T), sin deduplicar reseñas distintas.
- [topicos_comparacion/](topicos_comparacion/): comparación NMF, LDA y S-BERT/BERTopic; el modelo elegido es S-BERT/BERTopic con 41 tópicos.
- [latam_ampliacion/](latam_ampliacion/): construcción del corpus final PE/MX/AR (1.143.877 reseñas) con fuentes verificadas por SHA-256 y reanudación segura.
- [`../carga_sql_server/`](../carga_sql_server/README.md): carga Python/T-SQL del corpus final a SQL Server.

Los modelos, entornos virtuales, perfiles de navegador y checkpoints se generan localmente y no se versionan.

## Etapa 1 — Consultas de búsqueda
| Script | Qué hace |
|---|---|
| `prepare_mexico_geography.py`, `prepare_argentina_geography.py` | Preparan los 3 insumos geográficos de cada país (límite, divisiones, tabla de unidades). |
| `build_queries.py` | Construye la lista de consultas para `mapScraper` (`data/referencia/queries_busqueda*.csv`). |
| `country_config.py` | Lee y valida `data/referencia/paises_latam.csv` (configuración por país). |

## Etapa 2 — Búsqueda de lugares
| Script | Qué hace |
|---|---|
| `run_full_search.py` | Corrida masiva y reanudable de búsqueda (`--codigo-pais`, `--consolidate-only`). |
| `run_search_batch.py` | Corre un lote de consultas contra `mapScraper`. |

## Etapa 3 — Depuración y universo de museos
| Script | Qué hace |
|---|---|
| `process_lugares_etapa3.py` | Depuración, validación geográfica y clasificación por país → `data/lugares/base_museos_<pais>.csv`. |
| `auditar_base_museos.py`, `export_revision_riesgo.py` | Auditoría de la base y lugares de mayor riesgo para revisión manual. |

## Etapa 4 — Extracción de reseñas
| Script | Qué hace |
|---|---|
| `scrape_museos_v2.py` | Extracción de Argentina: reanudable, estado en SQLite, `--perfil` con sesión de Google. |
| `scrape_museos_ii.py`, `scrape_comentarios_museos.py`, `run_full_reviews.py` | Extracción de Perú y México. |
| `scrape_qorikancha.py` | Extractor dedicado al museo de mayor volumen de Perú. |
| `login_google.py`, `check_sesion.py` | Iniciar y verificar la sesión de Google del perfil de Chrome (necesaria: sin sesión solo se obtienen 5 reseñas por lugar). |
| `preparar_piloto_museos.py` | Piloto de extracción sobre una muestra de museos. |
| `validar_conteos.py` | ¿Cuántas reseñas hay realmente disponibles por museo? |

## Etapa 5 — Consolidación, publicación y análisis
| Script | Qué hace |
|---|---|
| `consolidar_corpus.py` | Une las corridas de Perú (I–IV), Argentina (AR) y México (MX, si existe) deduplicando por `id_review`; agrega la columna `pais`. Lee los CSV o sus paquetes `.csv.gz`. Con `--desde-consolidado` parte del consolidado publicado y le suma las fuentes presentes (para quien no tiene los crudos de Perú II–IV). |
| `consolidate_latam.py`, `validar_latam.py` | Consolidado LATAM y validaciones de contrato. |
| `empaquetar_resenas.py` | Parte un CSV de reseñas en `.csv.gz` de <90 MB para subirlo a GitHub (`data/resenas/paquetes/`). |
| `build_eda_museos.py` | Genera el notebook exploratorio de `notebooks/` con `nbformat`. |
