# Depuración y homogeneización del datamart
Estos scripts ya están aplicados en el `.bak` entregado. Documentan las transformaciones realizadas sobre el datamart cargado y son idempotentes; no es necesario ejecutarlos para levantar el dashboard.

## 1. Depuración de columnas
`01_depuracion_columnas.sql` elimina 14 columnas de `mart.*` sin información (un solo valor en todas las filas, o 100 % vacías). Es idempotente.
El respaldo resultante es `MuseosLatam_Datamart_depurado_20261108.bak` (Release v1.0).

| Tabla | Columnas eliminadas | Motivo |
|---|---|---|
| dim_lugar | es_vigente, version | un solo valor (1) |
| dim_lugar | valido_desde, valido_hasta | 100 % NULL |
| fact_reputacion_lugar | fecha_observacion | 100 % NULL |
| fact_reputacion_lugar | precision_observacion, version_fuente, sk_periodo | un solo valor |
| fact_resena | hash_fuente, version_modelo_topicos | un solo valor |
| fact_resena_dimension | peso, es_dominante, hash_fuente | un solo valor |
| dim_dimension_latente | version_revision | un solo valor |

Efectos colaterales manejados: vistas `v_catalogo_topicos`, `v_dimension_satisfaccion` (peso=1 → `n_con_rating`, `rating_promedio`), `v_reputacion_territorial`; CHECK y DEFAULT asociados; FK a dim_tiempo de la reputación; la unicidad (sk_lugar, version_fuente) pasa a (sk_lugar); `sp_refreshview` en las vistas con `f.*`.
Verificación: huella (conteos + checksums de las columnas restantes) idéntica antes y después; las 10 vistas compilan; 16/16 pruebas de KPI.

---
# 2. Homogeneización geográfica y depuración adicional
`02_homogeneizacion_y_depuracion_adicional.sql` (idempotente; se aplica después del 01).

**A) Geografía** (`mart.dim_geografia`)
- `nivel3_nombre`: `''` → `NULL` en Argentina, México y el miembro desconocido (la columna pasa a admitir NULL). Antes "no existe nivel 3" se expresaba de dos formas (`''` en el nombre, `NULL` en el tipo).
- `codigo_nativo` de Perú (UBIGEO): se quita el `.0` residual de la conversión numérica (684 códigos, p. ej. `20201.0` → `20201`). **No** se modifica `nk_geografia` (hash de la clave natural) ni ninguna clave sustituta.
- Equivalencia entre países (las jerarquías ya estaban alineadas por nivel):

| Nivel | Argentina | México | Perú | Comparable entre países |
|---|---|---|---|---|
| 1 | provincia | estado | departamento | sí (primer nivel administrativo) |
| 2 | departamento o partido | municipio o alcaldía | provincia | sí (segundo nivel administrativo) |
| 3 | — (NULL) | — (NULL) | distrito | no: solo existe en Perú |

- Fuentes de código distintas: Argentina y México usan geoBoundaries (ADM2); Perú usa UBIGEO del INEI. Hay nombres repetidos dentro de una región (p. ej. Pilar, Bermejo, Tijuana, Bagua): son filas distintas con código distinto; agrupar siempre por `sk_geografia`/`codigo_nativo`, no por nombre.

**B) Campos redundantes eliminados**: `fact_resena.p_negativo`, `p_neutro`, `p_positivo`, `confianza_sentimiento`; `dim_rating.es_positiva`, `es_negativa`, `es_neutra` (derivables del rating); `dim_tiempo.trimestre`, `mes_nombre` (el 89 % de las fechas es solo año); `dim_geografia.pais_iso3` (queda `codigo_pais`).

**C) Idioma**: se elimina `fact_resena.sk_idioma` y la tabla `mart.dim_idioma` (con su FK). El corpus es mayoritariamente en español; el detector era poco fiable en textos cortos (193 mil "inciertas") y había ~2.000 reseñas realmente en inglés que ahora quedan sin marca de idioma. La vista `mart.v_resena_completa` se reescribió sin idioma ni trimestre.

Verificación: huella (conteos + checksums de las columnas restantes de hechos y dimensiones) idéntica antes y después; script ejecutado dos veces sin efecto; 0 vistas con error; capa BI reconstruida y 16/16 pruebas OK.
Se conservan `nk_id_review`, `source_row` y `hash_fila` (trazabilidad hacia la base de origen `MuseosLatam_Origen`).
