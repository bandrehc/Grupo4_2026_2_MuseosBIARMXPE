"""build_eda_museos.py — Genera notebooks/eda_museos.ipynb via nbformat.

EDA del corpus de la Etapa 4-M (reseñas de los 1081 museos de base_museos_peru.csv).

En comentarios_museos_crudo.csv la columna `categoria_google` es degenerada (un solo valor
"Museo"); la `categoria_normalizada` real se recupera con un join contra base_museos_peru.csv.

Incorpora las advertencias del perfilado de los datos:

  - review_date es una estimación: ~81 % de las reseñas solo tiene precisión de año, por eso
    no se grafica nada por debajo de granularidad mensual.
  - ~45 % de las reseñas no tiene texto: los KPI de texto llevan su propio denominador.
  - la columna `reviews` no es el techo de cobertura.

No ejecuta el notebook (eso se hace con jupyter nbconvert --execute), solo lo construye.
"""
from pathlib import Path
import nbformat as nbf

PROJECT_ROOT = Path(__file__).resolve().parent.parent

nb = nbf.v4.new_notebook()
cells = []


def md(text):
    cells.append(nbf.v4.new_markdown_cell(text))


def code(text):
    cells.append(nbf.v4.new_code_cell(text))


md("""# EDA — Corpus de reseñas de museos del Perú (Etapa 4-M)

Análisis exploratorio de las reseñas de Google Maps extraídas para los **1081 museos** de
`data/lugares/base_museos_peru.csv`.

## Cómo leer este notebook

Tres advertencias de calidad de datos condicionan qué se puede concluir; cada una se repite en
la sección donde aplica:

| # | Advertencia | Consecuencia |
|---|---|---|
| **A** | `review_date` no es un dato de Google: se estima restando `relative_date` a la fecha de extracción | ~81 % de las reseñas solo tiene precisión de **año**. No se grafica por debajo de mes. |
| **B** | ~45 % de las reseñas **no tiene texto** (son solo estrellas) | Los KPI de texto usan su propio denominador, no el total. |
| **C** | La columna `reviews` mide algo distinto de lo que sirve el panel de Google | No usarla como denominador de cobertura. |

Un cuarto punto, sobre el universo mismo: el 71,7 % de los
1081 museos no tiene "museo" en el nombre, y muchas entradas son dudosas como museos. Los
resultados agregados deben leerse con eso presente.
""")

code("""import re
import unicodedata
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_theme(style="whitegrid")
plt.rcParams["figure.figsize"] = (10, 5)
pd.set_option("display.max_columns", 60)

PROJECT_ROOT = Path.cwd().parent
""")

# ── 1. Carga ─────────────────────────────────────────────────────────────────
md("""## 1. Carga, join e integridad

Se unen las reseñas con la base de museos para recuperar `categoria_normalizada`, geografía
y las métricas que Google reportaba al momento de la búsqueda.

**Clave de join**: `google_place_id` (reseñas) ↔ `id` (base de museos).
""")

code("""museos  = pd.read_csv(PROJECT_ROOT / "data" / "lugares" / "base_museos_peru.csv")
resenas = pd.read_csv(PROJECT_ROOT / "data" / "resenas" / "comentarios_museos_crudo.csv")

# categoria_google es degenerada (un solo valor "Museo"): la categoria util viene del join.
cols_museo = ["id", "categoria_normalizada", "palabra_clave", "prioridad",
              "stars", "reviews", "lat", "lon", "departamento_final",
              "provincia_final", "distrito_final"]
resenas = resenas.merge(
    museos[cols_museo].rename(columns={"id": "google_place_id"}),
    on="google_place_id", how="left",
)

print(f"Museos en el universo:                    {len(museos):,}")
print(f"Reseñas extraídas:                        {len(resenas):,}")
print(f"Museos con al menos una reseña:           {resenas['google_place_id'].nunique():,}")
print(f"Avance de la extracción:                  {100*resenas['google_place_id'].nunique()/len(museos):.1f}%")
print(f"Reseñas sin match en la base de museos:   {resenas['categoria_normalizada'].isna().sum():,}")
""")

code("""print("--- Nulos en las reseñas ---")
nulos = resenas.isnull().sum()
print(nulos[nulos > 0].to_string())
print()
print(f"Duplicados por id_review: {resenas['id_review'].duplicated().sum()}")
print(f"Duplicados por (museo, id_review): {resenas.duplicated(['google_place_id','id_review']).sum()}")
print()
print(f"Rango de fechas estimadas: {resenas['review_date'].min()} .. {resenas['review_date'].max()}")
""")

# ── 2. Universo ──────────────────────────────────────────────────────────────
md("""## 2. El universo de museos

Distribución del universo completo (1081), independiente de cuántas reseñas se hayan
extraído. Se usa `categoria_normalizada` —la taxonomía del proyecto— y no `categoria_google`,
que tiene un único valor y no discrimina nada.
""")

code("""fig, axes = plt.subplots(1, 2, figsize=(15, 6))

museos["departamento_final"].value_counts().sort_values().plot(
    kind="barh", ax=axes[0], color="#2E6F63")
axes[0].set_title("Museos por departamento")
axes[0].set_xlabel("Museos")

museos["categoria_normalizada"].value_counts().plot(
    kind="barh", ax=axes[1], color="#9C5A24")
axes[1].set_title("Museos por categoría normalizada")
axes[1].set_xlabel("Museos")

plt.tight_layout(); plt.show()

print(museos["categoria_normalizada"].value_counts().to_string())
""")

code("""# Señal de calidad del universo
def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFKD", str(s))
                   if not unicodedata.combining(c)).upper()

museos["museo_en_titulo"] = museos["title"].map(
    lambda t: bool(re.search(r"MUSE(O|UM)", sin_tildes(t))))

resumen = museos.groupby("museo_en_titulo")["reviews"].agg(
    museos="size", mediana_resenas="median", pct_hasta_10=lambda s: 100*(s <= 10).mean())
resumen.index = ["Sin 'museo' en el título", "Con 'museo' en el título"]
print(resumen.round(1).to_string())
print()
print("Los que no llevan 'museo' en el nombre tienen sistemáticamente menos reseñas.")
""")

# ── 3. Calificaciones ────────────────────────────────────────────────────────
md("""## 3. Calificaciones

`rating` es una métrica semi-aditiva: el promedio correcto es `SUM(rating)/COUNT(*)`.
Promediar promedios por museo daría un número distinto y equivocado.
""")

code("""fig, axes = plt.subplots(1, 2, figsize=(15, 5))

resenas["rating"].value_counts().sort_index().plot(
    kind="bar", ax=axes[0], color="#2E6F63")
axes[0].set_title(f"Distribución de calificaciones (promedio global {resenas['rating'].mean():.2f})")
axes[0].set_xlabel("Estrellas"); axes[0].set_ylabel("Reseñas")

orden = resenas.groupby("categoria_normalizada")["rating"].median().sort_values().index
sns.boxplot(data=resenas, y="categoria_normalizada", x="rating", order=orden, ax=axes[1])
axes[1].set_title("Calificación por categoría")

plt.tight_layout(); plt.show()
""")

code("""top = (resenas.groupby(["google_place_id", "nombre_lugar"])
       .agg(n_resenas=("rating", "size"), rating_promedio=("rating", "mean"))
       .sort_values("n_resenas", ascending=False))
print("=== 15 museos con más reseñas extraídas ===")
print(top.head(15).round(2).to_string())
""")

# ── 4. Precisión temporal ────────────────────────────────────────────────────
md("""## 4. Precisión temporal — leer antes de cualquier serie de tiempo

Google **no publica** la fecha en que se escribió una reseña: solo una etiqueta relativa
("Hace 6 meses"). El scraper deriva `review_date` restando esa etiqueta al momento de
extracción, con mes = 30 días y año = 365 días.

Por eso `review_date` tiene apariencia de precisión (llega a microsegundos) que **no
corresponde a la realidad**. Esta sección mide cuánta precisión hay de verdad.
""")

code("""def precision_de(rel):
    s = str(rel).lower()
    if "segundo" in s or "minuto" in s or "hora" in s or "día" in s or "dia" in s:
        return "DIA"
    if "semana" in s:
        return "SEMANA"
    if "mes" in s:
        return "MES"
    if "año" in s or "ano" in s:
        return "AÑO"
    return "NA"

resenas["precision_fecha"] = resenas["relative_date"].map(precision_de)
dist = resenas["precision_fecha"].value_counts()
pct = (100 * dist / len(resenas)).round(1)

print("=== Precisión REAL de la fecha de reseña ===")
print(pd.DataFrame({"reseñas": dist, "%": pct}).to_string())
print()
print(f"El {pct.get('AÑO', 0)}% de las reseñas solo puede ubicarse dentro de un año.")
print("  Por eso abajo no se grafica ninguna serie por debajo de granularidad mensual:")
print("  una curva diaria o semanal sería ruido inventado con apariencia de dato.")

dist.plot(kind="bar", color="#9C5A24")
plt.title("Precisión alcanzable de la fecha de reseña"); plt.ylabel("Reseñas")
plt.tight_layout(); plt.show()
""")

code("""# Serie MENSUAL — el grano mínimo defendible dado lo anterior
resenas["mes"] = pd.to_datetime(resenas["review_date"], errors="coerce").dt.to_period("M")
serie = resenas.groupby("mes").agg(n_resenas=("rating", "size"),
                                   rating_promedio=("rating", "mean"))
serie = serie[serie.index.notna()].tail(48)

fig, ax1 = plt.subplots(figsize=(13, 5))
serie["n_resenas"].plot(ax=ax1, color="#2E6F63", label="Reseñas")
ax1.set_ylabel("Reseñas por mes"); ax1.set_xlabel("Mes (estimado)")
ax2 = ax1.twinx()
serie["rating_promedio"].plot(ax=ax2, color="#9C5A24", linestyle="--", label="Rating")
ax2.set_ylabel("Rating promedio"); ax2.set_ylim(1, 5)
plt.title("Volumen y calificación por mes — fechas ESTIMADAS (ver advertencia arriba)")
plt.tight_layout(); plt.show()
""")

# ── 5. Cobertura ─────────────────────────────────────────────────────────────
md("""## 5. Cobertura de extracción — con el denominador correcto

Hay **dos conteos distintos** de reseñas y no miden lo mismo:

- `reviews` (columna de la base) viene del **listado de búsqueda** de la Etapa 2.
- Lo que el **panel del lugar** sirve es bastante menos, y es el 100 % de lo que el scraper
  logra extraer.

Verificado: donde la base dice 118, el panel declara 29 y se extraen las 29. Usar `reviews`
como denominador da una cobertura falsamente catastrófica.

Requiere haber corrido antes:
`python3 repos_wrapper/scrape_comentarios_museos.py --consolidate-only`
""")

code("""ruta_cob = PROJECT_ROOT / "data" / "resenas" / "cobertura_museos_por_lugar.csv"
if not ruta_cob.exists():
    print("Falta cobertura_museos_por_lugar.csv — correr primero --consolidate-only.")
else:
    cob = pd.read_csv(ruta_cob)
    print("=== Estado de la extracción ===")
    print(cob["status"].value_counts().to_string())
    print()
    print(f"Reseñas extraídas en total:        {int(cob['n_reviews_obtenidas_real'].sum()):,}")
    print(f"Museos con al menos una reseña:    {int((cob['n_reviews_obtenidas_real'] > 0).sum()):,}")
    print()
    sosp = cob[cob["sospechoso_cero_resenas"]]
    if len(sosp):
        print(f"{len(sosp)} museos marcados 'completado' con 0 reseñas extraídas.")
        print("  No se reintentan solos (get_pending ignora 'completado').")
        print(sosp.nlargest(8, "n_reviews_google")[["nombre", "n_reviews_google"]].to_string(index=False))
""")

code("""if ruta_cob.exists():
    por_depto = (cob.groupby("departamento")
                 .agg(museos=("lugar_id", "size"),
                      resenas=("n_reviews_obtenidas_real", "sum"))
                 .sort_values("resenas", ascending=False))
    print(por_depto.head(15).to_string())

    por_depto["resenas"].head(15).sort_values().plot(kind="barh", color="#2E6F63")
    plt.title("Reseñas extraídas por departamento"); plt.xlabel("Reseñas")
    plt.tight_layout(); plt.show()
""")

# ── 6. Texto ─────────────────────────────────────────────────────────────────
md("""## 6. Análisis de texto — con su propio denominador

Cerca del **45 % de las reseñas no tiene texto**: son calificaciones de solo estrellas. El
universo del análisis cuantitativo y el del análisis textual son poblaciones distintas.

Todo lo que sigue se calcula **solo sobre las reseñas con texto**, y ese denominador se
declara explícitamente en cada resultado.
""")

code("""con_texto = resenas[resenas["caption"].notna()].copy()
pct_texto = 100 * len(con_texto) / len(resenas)

print(f"Reseñas totales:      {len(resenas):,}")
print(f"Reseñas CON texto:    {len(con_texto):,}  ({pct_texto:.1f}%)")
print(f"Reseñas SIN texto:    {len(resenas) - len(con_texto):,}  ({100-pct_texto:.1f}%)")
print()
print("Todo lo que sigue usa el denominador de reseñas CON texto, no el total.")

con_texto["n_palabras"] = con_texto["caption"].str.split().str.len()
print()
print(con_texto["n_palabras"].describe().round(1).to_string())
""")

code("""STOPWORDS = set(\"\"\"
a al algo algunas algunos ante antes como con contra cual cuando de del desde donde dos el
ella ellas ellos en entre era eran es esa ese eso esta estan este esto estos fue fueron ha
hasta hay la las le les lo los mas me mi mucho muy no nos o os otra otro para pero poco por
porque que quien se ser si sin sobre solo son su sus tambien tanto te tiene todo todos tu un
una uno unos y ya lugar puede hace bien alli ahi asi mismo cada tan
\"\"\".split())

def tokenizar(texto):
    t = "".join(c for c in unicodedata.normalize("NFKD", str(texto).lower())
                if not unicodedata.combining(c))
    return [w for w in re.findall(r"[a-zñ]{3,}", t) if w not in STOPWORDS]

tokens = con_texto["caption"].map(tokenizar)
frec = Counter(w for lista in tokens for w in lista)

print(f"=== 20 palabras más frecuentes (sobre {len(con_texto):,} reseñas con texto) ===")
for palabra, n in frec.most_common(20):
    print(f"  {palabra:<18} {n:>6}")

pd.Series(dict(frec.most_common(20))).sort_values().plot(kind="barh", color="#2E6F63")
plt.title(f"Palabras más frecuentes (n={len(con_texto):,} reseñas con texto)")
plt.tight_layout(); plt.show()
""")

code("""# Vocabulario diferencial: qué distingue a las reseñas positivas de las negativas
alta = con_texto[con_texto["rating"] >= 4]["caption"].map(tokenizar)
baja = con_texto[con_texto["rating"] <= 2]["caption"].map(tokenizar)

f_alta = Counter(w for l in alta for w in l)
f_baja = Counter(w for l in baja for w in l)
n_alta = max(sum(f_alta.values()), 1)
n_baja = max(sum(f_baja.values()), 1)

print(f"Reseñas con texto y rating >=4: {len(alta):,}")
print(f"Reseñas con texto y rating <=2: {len(baja):,}")
print()

# frecuencia relativa: evita que las palabras comunes dominen ambas listas
distintivas_baja = sorted(
    ((w, f_baja[w]/n_baja - f_alta.get(w, 0)/n_alta, f_baja[w])
     for w in f_baja if f_baja[w] >= 5),
    key=lambda x: -x[1])[:15]

print("=== Palabras más distintivas de las reseñas NEGATIVAS ===")
for w, dif, n in distintivas_baja:
    print(f"  {w:<18} {n:>5} apariciones")
""")

md("""## 7. Síntesis

Al interpretar cualquier resultado de arriba, tener presente:

1. **Las fechas son estimadas** (A) — no hay conclusiones válidas sobre estacionalidad fina.
2. **Los KPI de texto cubren ~55 % del corpus** (B).
3. **La cobertura se mide contra el panel**, no contra la columna `reviews` (C).
4. **El universo tiene ruido conocido**: 71,7 % de los museos no lleva "museo" en el nombre.
   Conviene repetir los cortes principales restringiendo a
   los museos de confianza alta antes de publicar conclusiones.
""")

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.13"},
}

out_path = PROJECT_ROOT / "notebooks" / "eda_museos.ipynb"
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    nbf.write(nb, f)
print(f"Notebook generado: {out_path}  ({len(cells)} celdas)")
