# Configuración de países LATAM

`paises_latam.csv` es el registro único de configuración para los países que
puede manejar el pipeline. No inicia ninguna descarga, búsqueda ni scraping.
Las etapas leen este archivo en vez de incorporar condicionales por país en cada script.

## Campos

- `codigo_pais`: ISO 3166-1 alpha-2, usado en el consolidado LATAM.
- `pais`: nombre a mostrar y el que debe aparecer en el texto de las queries.
- `slug_pais`: nombre ASCII para construir rutas aisladas de outputs y estados.
- `google_country_code` e `idioma`: valores que se pasarán a `mapScraper` como
  `--country` y `--lang`.
- `nivel_1_nombre`, `nivel_2_nombre`, `nivel_3_nombre`: significado local de
  las columnas históricas `departamento`, `provincia` y `distrito`.
- `archivo_*`: archivos relativos a esta carpeta que se requieren para ejecutar
  discovery y validación espacial.
- `columna_unidad_*` y `columna_division_*`: nombres de las columnas o
  propiedades fuente que el adaptador deberá mapear a los campos históricos.
- `estado_geografia`: `disponible` solo permite ejecución; `pendiente` debe
  producir un error claro que enumere los archivos faltantes.

## Contrato mínimo de los insumos geográficos

Cada país requiere tres archivos en `data/referencia/`:

1. `archivo_unidades_query`: CSV para generar queries. Debe tener los campos
   configurados en `columna_unidad_id`, `columna_unidad_departamento`,
   `columna_unidad_provincia` y `columna_unidad_distrito`. Los niveles sin una
   equivalencia confiable pueden quedar vacíos.
2. `archivo_boundary`: GeoJSON de límite nacional (ADM0) en EPSG:4326.
3. `archivo_divisiones`: GeoJSON de divisiones administrativas en EPSG:4326;
   sus propiedades se especifican con las cuatro columnas `columna_division_*`.

El adaptador de la Etapa 3 conservará los nombres de salida
`departamento_final`, `provincia_final` y `distrito_final`. No se crea un
nivel administrativo inexistente: un valor no confiable se mantiene nulo.

## Convención de aislamiento por país

La resolución de rutas se basa en `slug_pais`; por ejemplo, para México:

```text
data/referencia/queries_busqueda_mx.csv
data/lugares/_raw_incremental_mx.csv
data/lugares/lugares_candidatos_mexico.csv
data/lugares/lugares_identificados_mexico.csv
data/lugares/base_museos_mexico.csv
data/resenas/comentarios_museos_crudo_mexico.csv
data/resenas/resenas_museos_consolidadas_mexico.csv
logs/estado_busqueda_mx.db
logs/estado_scraping_museos_mx.db
```

La configuración de Perú apunta a sus insumos originales y no sobrescribe sus salidas.

## Uso por los wrappers generalizados

Los países nuevos se ejecutan indicando su código ISO en todos los wrappers;
las rutas se resuelven de forma aislada a partir de la configuración:

```powershell
cd repos_wrapper
python build_queries.py --country MX --out ../data/referencia/queries_busqueda_mx.csv
python run_full_search.py --codigo-pais MX --limit 20 --concurrent 2
python process_lugares_etapa3.py --country MX
python scrape_comentarios_museos.py --country MX --max-reviews 30000 --concurrent 3
python consolidate_latam.py
```

Los tres comandos fallan antes de procesar si el país permanece en
`estado_geografia=pendiente`. `process_lugares_etapa3.py` genera para un país
nuevo su `base_museos_<slug>.csv` mediante el filtro exacto
`category == "Museo"`. Para Perú ese archivo histórico no se regenera por
defecto, aunque el script conserve sus rutas de entrada y salida tradicionales.
El scraper nacional conserva las 16 columnas históricas de reseñas; añade país
únicamente al consolidado LATAM de una fase posterior. Sus SQLite, CSV crudo,
consolidado y cobertura quedan aislados por `slug_pais`.

`consolidate_latam.py` crea una tabla raw plana con `pais` y `codigo_pais`,
deduplicada globalmente por `google_place_id + id_review`, y
`data/resenas/progreso_resenas_latam.csv`. Este último expone reseñas únicas,
faltantes a la meta, museos con reseñas y estados de scraping por país.

## Alta de un país

1. Añadir una fila con un `codigo_pais`, `slug_pais` y códigos Google únicos.
2. Documentar fuente, fecha, licencia y cobertura de los tres insumos
   geográficos.
3. Cambiar `estado_geografia` a `disponible` solo después de validar archivos,
   CRS y columnas configuradas.
4. Ejecutar un piloto pequeño antes de una búsqueda nacional.
