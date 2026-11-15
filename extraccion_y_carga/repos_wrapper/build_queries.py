"""build_queries.py — Construye la lista de consultas de búsqueda para mapScraper.

Combina cada palabra clave de data/referencia/categorias.csv con las unidades
geográficas configuradas para un país en data/referencia/paises_latam.csv. La
salida conserva los campos históricos distrito/provincia/departamento para que
las etapas posteriores sigan siendo compatibles.

Uso
----
  # Lista completa (todo el Perú, las ~31k queries de producción)
  python build_queries.py --out ../data/referencia/queries_busqueda.csv

  # Otro país habilitado en paises_latam.csv
  python build_queries.py --country MX --out ../data/referencia/queries_busqueda_mx.csv

  # Subconjunto piloto: solo ciertos departamentos, solo keywords de prioridad alta,
  # y como maximo N distritos por departamento (muestreo representativo, no todos)
  python build_queries.py --departamentos CUSCO,LIMA,ANCASH --prioridad alta \
      --max-distritos-por-departamento 4 --out ../data/lugares/pilot_queries.csv
"""
import argparse
import unicodedata
from pathlib import Path

import pandas as pd

from country_config import load_country_config

REF_DIR = Path(__file__).resolve().parent.parent / "data" / "referencia"


def _titlecase(s: str) -> str:
    return " ".join(w.capitalize() for w in str(s).strip().split())


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _dedupe_tokens(tokens):
    """Quita tokens consecutivos repetidos (ignorando acentos/mayusculas)."""
    out = []
    prev_norm = None
    for t in tokens:
        norm = _strip_accents(t).lower()
        if norm != prev_norm:
            out.append(t)
        prev_norm = norm
    return out


def build_query_text(termino_plural: str, *lugares: str, pais: str = "Perú") -> str:
    lugares_fmt = [_titlecase(l) for l in lugares if l and str(l).strip()]
    lugares_fmt = _dedupe_tokens(lugares_fmt)
    return f"{termino_plural} en {', '.join(lugares_fmt)}, {pais}"


def load_geografia(country: pd.Series) -> pd.DataFrame:
    """Mapea la fuente geográfica del país al contrato histórico de queries.

    `inei` se conserva como nombre de columna de salida por compatibilidad con
    los artefactos de Perú. Para otro país contiene el identificador configurado
    en `columna_unidad_id`, sin implicar que sea un código INEI.
    """
    path = REF_DIR / country["archivo_unidades_query"]
    if not path.is_file():
        raise FileNotFoundError(
            f"No existe el archivo de unidades de query configurado para "
            f"{country['pais']}: {path}"
        )
    source = pd.read_csv(path, dtype=str)
    source_columns = {
        "inei": country["columna_unidad_id"],
        "departamento": country["columna_unidad_departamento"],
        "provincia": country["columna_unidad_provincia"],
        "distrito": country["columna_unidad_distrito"],
    }
    missing = [column for column in source_columns.values() if column not in source.columns]
    if missing:
        raise ValueError(
            f"{path.name} no cumple la configuración de {country['pais']}; "
            f"faltan columnas: {', '.join(sorted(set(missing)))}"
        )

    df = source[list(source_columns.values())].rename(
        columns={source_column: target for target, source_column in source_columns.items()}
    )
    # Un país puede no tener un tercer nivel confiable (México usa municipio en
    # `provincia` y deja `distrito` vacío). Solo el nivel superior es obligatorio;
    # los niveles faltantes no se inventan ni hacen desaparecer la unidad.
    df = df.dropna(subset=["departamento"]).copy()
    df["provincia"] = df["provincia"].fillna("")
    df["distrito"] = df["distrito"].fillna("")
    return df


def load_ubigeo() -> pd.DataFrame:
    """Alias histórico para consumidores externos que aún esperan Perú."""
    return load_geografia(load_country_config("PE"))


def load_categorias(prioridad: str | None = None, archivo: str = "categorias.csv") -> pd.DataFrame:
    df = pd.read_csv(REF_DIR / archivo)
    if prioridad:
        prioridades = {p.strip().lower() for p in prioridad.split(",")}
        df = df[df["prioridad"].str.lower().isin(prioridades)]
    return df


def sample_by_departamento(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Muestra hasta ``n`` unidades por nivel superior sin perder columnas.

    Se evita ``groupby.apply``: pandas recientes excluyen la columna de grupo
    de la función y rompían la construcción de queries de países sin distrito.
    """
    samples = [
        group.sample(n=min(len(group), n), random_state=42)
        for _, group in df.groupby("departamento", sort=False)
    ]
    return pd.concat(samples, ignore_index=True) if samples else df.iloc[0:0].copy()


def build_queries(
    ubigeo: pd.DataFrame,
    categorias: pd.DataFrame,
    departamentos: list[str] | None = None,
    max_distritos_por_departamento: int | None = None,
    max_unidades_por_departamento: int | None = None,
    niveles: tuple[str, ...] = ("distrito", "provincia", "departamento"),
    pais: str = "Perú",
) -> pd.DataFrame:
    if departamentos:
        deps_norm = {_strip_accents(d).upper() for d in departamentos}
        ubigeo = ubigeo[
            ubigeo["departamento"].apply(lambda d: _strip_accents(d).upper()) .isin(deps_norm)
        ]

    rows = []

    # --- nivel distrito ---
    if "distrito" in niveles:
        ubi_distrito = ubigeo[ubigeo["distrito"].fillna("").astype(str).str.strip().ne("")]
        sample_size = max_distritos_por_departamento or max_unidades_por_departamento
        if sample_size:
            ubi_distrito = sample_by_departamento(ubi_distrito, sample_size)
        for _, u in ubi_distrito.iterrows():
            for _, c in categorias.iterrows():
                rows.append({
                    "query_text": build_query_text(
                        c["termino_busqueda_plural"], u["distrito"], u["provincia"], u["departamento"], pais=pais
                    ),
                    "nivel": "distrito",
                    "palabra_clave": c["palabra_clave"],
                    "categoria_normalizada": c["categoria_normalizada"],
                    "prioridad": c["prioridad"],
                    "distrito": _titlecase(u["distrito"]),
                    "provincia": _titlecase(u["provincia"]),
                    "departamento": _titlecase(u["departamento"]),
                    "inei": u["inei"],
                })

    # --- nivel provincia ---
    if "provincia" in niveles:
        provincias = ubigeo.drop_duplicates(subset=["departamento", "provincia"])
        if max_unidades_por_departamento:
            provincias = sample_by_departamento(provincias, max_unidades_por_departamento)
        for _, u in provincias.iterrows():
            for _, c in categorias.iterrows():
                rows.append({
                    "query_text": build_query_text(
                        c["termino_busqueda_plural"], u["provincia"], u["departamento"], pais=pais
                    ),
                    "nivel": "provincia",
                    "palabra_clave": c["palabra_clave"],
                    "categoria_normalizada": c["categoria_normalizada"],
                    "prioridad": c["prioridad"],
                    "distrito": "",
                    "provincia": _titlecase(u["provincia"]),
                    "departamento": _titlecase(u["departamento"]),
                    "inei": u["inei"][:4] if isinstance(u["inei"], str) else "",
                })

    # --- nivel departamento ---
    if "departamento" in niveles:
        departamentos_df = ubigeo.drop_duplicates(subset=["departamento"])
        for _, u in departamentos_df.iterrows():
            for _, c in categorias.iterrows():
                rows.append({
                    "query_text": build_query_text(c["termino_busqueda_plural"], u["departamento"], pais=pais),
                    "nivel": "departamento",
                    "palabra_clave": c["palabra_clave"],
                    "categoria_normalizada": c["categoria_normalizada"],
                    "prioridad": c["prioridad"],
                    "distrito": "",
                    "provincia": "",
                    "departamento": _titlecase(u["departamento"]),
                    "inei": u["inei"][:2] if isinstance(u["inei"], str) else "",
                })

    # Dedup solo DENTRO de cada nivel (distrito/provincia/departamento), nunca entre
    # niveles: un distrito que se llama igual que su provincia y departamento (ej.
    # "Lima" distrito / "Lima" provincia / "Lima" departamento) produce el mismo texto
    # de query en los 3 niveles, y eso es intencional (son 3 unidades geograficas
    # distintas aunque el texto colapsado coincida) — deduplicar entre niveles borraba
    # departamentos enteros de forma silenciosa.
    out = pd.DataFrame(rows).drop_duplicates(subset=["nivel", "query_text"]).reset_index(drop=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="Ruta del CSV de salida")
    ap.add_argument("--country", "--codigo-pais", dest="codigo_pais", default="PE",
                    help="Código ISO alpha-2 configurado en paises_latam.csv (default: PE)")
    ap.add_argument("--departamentos", default=None,
                    help="Valores del nivel administrativo superior, separados por coma (ej. CUSCO,LIMA,ANCASH). Default: todos")
    ap.add_argument("--prioridad", default=None, help="Filtrar categorias por prioridad (ej. alta o alta,opcional). Default: todas")
    ap.add_argument("--max-distritos-por-departamento", type=int, default=None, help="Muestreo: max distritos por departamento (para pilotos). Default: todos")
    ap.add_argument("--max-unidades-por-departamento", type=int, default=None,
                    help="Muestreo por nivel más específico disponible; útil cuando no existe distrito confiable.")
    ap.add_argument("--categorias", default="categorias.csv",
                    help="CSV de palabras clave dentro de data/referencia (default: categorias.csv; AR: categorias_ar.csv)")
    ap.add_argument("--niveles", default="distrito,provincia,departamento", help="Niveles a incluir, separados por coma")
    args = ap.parse_args()

    country = load_country_config(args.codigo_pais)
    ubigeo = load_geografia(country)
    categorias = load_categorias(args.prioridad, args.categorias)
    departamentos = args.departamentos.split(",") if args.departamentos else None
    niveles = tuple(n.strip() for n in args.niveles.split(","))

    df = build_queries(
        ubigeo, categorias,
        departamentos=departamentos,
        max_distritos_por_departamento=args.max_distritos_por_departamento,
        max_unidades_por_departamento=args.max_unidades_por_departamento,
        niveles=niveles,
        pais=country["pais"],
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8")
    print(f"Generadas {len(df)} queries para {country['pais']} ({country['codigo_pais']}) -> {out_path}")
    print(df["nivel"].value_counts())


if __name__ == "__main__":
    main()
