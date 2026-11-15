"""Auditoría reproducible de una base nacional de museos.

No modifica la base ni los checkpoints. Produce reportes derivados para revisar:
  - contrato mínimo e integridad de Place IDs;
  - cobertura por nivel administrativo disponible en la configuración;
  - señal referencial de volumen de reseñas mostrada en la búsqueda;
  - posibles colisiones: mismo nombre normalizado y distancia <= 1 km;
  - muestra manual estratificada por unidad de primer nivel.

Ejemplo (PowerShell, desde museos_de_america):
  python repos_wrapper\auditar_base_museos.py --country MX
"""
import argparse
import itertools
import math
import re
import unicodedata
from pathlib import Path

import pandas as pd

from country_config import asset_path, load_country_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_LUGARES = PROJECT_ROOT / "data" / "lugares"


def normalizar(value: object) -> str:
    """Normaliza texto para comparar nombres, no para reemplazarlo en los datos."""
    text = "" if pd.isna(value) else str(value)
    text = "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def haversine_metros(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    radio = 6_371_000
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    delta_phi = math.radians(lat_b - lat_a)
    delta_lambda = math.radians(lon_b - lon_a)
    formula = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radio * math.asin(math.sqrt(formula))


def default_base_path(country: pd.Series) -> Path:
    return DATA_LUGARES / f"base_museos_{country['slug_pais']}.csv"


def require_columns(frame: pd.DataFrame, required: set[str]) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("La base no tiene las columnas requeridas: " + ", ".join(missing))


def coverage_report(base: pd.DataFrame, country: pd.Series) -> tuple[pd.DataFrame, dict[str, int]]:
    """Compara unidades consultables contra unidades donde se identificó un museo.

    Tener cero museos en una unidad no es una falla: puede no haber museo, puede
    no estar indexado por Google o el conjunto de queries puede no recuperarlo.
    Por eso esta salida mide cobertura observada, no exhaustividad garantizada.
    """
    geography = pd.read_csv(asset_path(country, "archivo_unidades_query"), dtype=str).fillna("")
    department_column = country["columna_unidad_departamento"]
    province_column = country["columna_unidad_provincia"]
    if not department_column or not province_column:
        raise ValueError("La configuración requiere columnas de primer y segundo nivel administrativo.")
    require_columns(geography, {department_column, province_column})

    expected = geography[[department_column, province_column]].copy()
    expected["_departamento_key"] = expected[department_column].map(normalizar)
    expected["_provincia_key"] = expected[province_column].map(normalizar)
    expected = expected[(expected["_departamento_key"] != "") & (expected["_provincia_key"] != "")]
    expected = expected.drop_duplicates(["_departamento_key", "_provincia_key"])

    observed = base[["departamento_final", "provincia_final"]].copy()
    observed["_departamento_key"] = observed["departamento_final"].map(normalizar)
    observed["_provincia_key"] = observed["provincia_final"].map(normalizar)
    observed = observed[(observed["_departamento_key"] != "") & (observed["_provincia_key"] != "")]
    observed = observed.drop_duplicates(["_departamento_key", "_provincia_key"])

    expected_by_department = (
        expected.groupby("_departamento_key", as_index=False)
        .agg(
            departamento_referencia=(department_column, "first"),
            unidades_referencia=("_provincia_key", "nunique"),
        )
    )
    found_by_department = (
        base.assign(
            _departamento_key=base["departamento_final"].map(normalizar),
            _provincia_key=base["provincia_final"].map(normalizar),
        )
        .groupby("_departamento_key", as_index=False)
        .agg(
            museos_identificados=("id", "size"),
            unidades_con_museo=("_provincia_key", lambda values: values[values.ne("")].nunique()),
        )
    )
    report = expected_by_department.merge(found_by_department, how="outer", on="_departamento_key")
    report["departamento"] = report["departamento_referencia"].fillna("")
    missing_name = report["departamento"].eq("")
    report.loc[missing_name, "departamento"] = report.loc[missing_name, "_departamento_key"]
    report["unidades_referencia"] = report["unidades_referencia"].fillna(0).astype(int)
    report["museos_identificados"] = report["museos_identificados"].fillna(0).astype(int)
    report["unidades_con_museo"] = report["unidades_con_museo"].fillna(0).astype(int)
    report["cobertura_unidades_observada_pct"] = (
        100 * report["unidades_con_museo"] / report["unidades_referencia"].replace(0, pd.NA)
    ).round(2)
    report = report[
        ["departamento", "unidades_referencia", "unidades_con_museo", "cobertura_unidades_observada_pct", "museos_identificados"]
    ].sort_values(["museos_identificados", "departamento"], ascending=[False, True])
    totals = {
        "departamentos_referencia": int(expected["_departamento_key"].nunique()),
        "departamentos_con_museo": int(observed["_departamento_key"].nunique()),
        "unidades_referencia": int(len(expected)),
        "unidades_con_museo": int(len(observed)),
    }
    return report, totals


def possible_collisions(base: pd.DataFrame, max_distance_meters: float = 1_000) -> pd.DataFrame:
    """Devuelve pares para revisión; no elimina ninguno automáticamente."""
    fields = ["id", "title", "lat", "lon", "departamento_final", "provincia_final"]
    work = base[fields].copy()
    work["_title_key"] = work["title"].map(normalizar)
    work["_department_key"] = work["departamento_final"].map(normalizar)
    rows: list[dict] = []
    grouped = work[(work["_title_key"] != "") & (work["_department_key"] != "")].groupby(
        ["_department_key", "_title_key"], sort=False
    )
    for (_, title_key), group in grouped:
        if len(group) < 2:
            continue
        for left, right in itertools.combinations(group.to_dict("records"), 2):
            distance = haversine_metros(left["lat"], left["lon"], right["lat"], right["lon"])
            if distance <= max_distance_meters:
                rows.append({
                    "titulo_normalizado": title_key,
                    "distancia_metros": round(distance, 1),
                    "id_1": left["id"],
                    "titulo_1": left["title"],
                    "provincia_1": left["provincia_final"],
                    "lat_1": left["lat"],
                    "lon_1": left["lon"],
                    "id_2": right["id"],
                    "titulo_2": right["title"],
                    "provincia_2": right["provincia_final"],
                    "lat_2": right["lat"],
                    "lon_2": right["lon"],
                    "accion": "Revisar manualmente; no se deduplicó por nombre ni distancia.",
                })
    return pd.DataFrame(rows).sort_values("distancia_metros") if rows else pd.DataFrame(columns=[
        "titulo_normalizado", "distancia_metros", "id_1", "titulo_1", "provincia_1", "lat_1", "lon_1",
        "id_2", "titulo_2", "provincia_2", "lat_2", "lon_2", "accion",
    ])


def manual_sample(base: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Dos casos por primer nivel: mayor señal de reseñas y un caso aleatorio."""
    work = base.copy()
    work["_department_key"] = work["departamento_final"].map(normalizar)
    work["_reviews_numeric"] = pd.to_numeric(work["reviews"], errors="coerce")
    samples: list[pd.DataFrame] = []
    for _, group in work[work["_department_key"].ne("")].groupby("_department_key", sort=True):
        top = group.sort_values(["_reviews_numeric", "id"], ascending=[False, True]).head(1).copy()
        top["tipo_muestra"] = "mayor_senal_reseñas_google"
        samples.append(top)
        remaining = group.loc[~group["id"].isin(top["id"])].copy()
        if not remaining.empty:
            random_row = remaining.sample(n=1, random_state=seed).copy()
            random_row["tipo_muestra"] = "aleatoria_estratificada"
            samples.append(random_row)
    result = pd.concat(samples, ignore_index=True)
    columns = [
        "tipo_muestra", "id", "title", "category", "address", "url_place", "stars", "reviews",
        "departamento_final", "provincia_final", "lat", "lon", "source_query", "query_text",
    ]
    return result[columns].sort_values(["departamento_final", "tipo_muestra", "title"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--country", default="MX", help="Código ISO alpha-2 configurado (default: MX).")
    parser.add_argument("--base", default=None, help="CSV base; default: base_museos_<pais>.csv.")
    parser.add_argument("--out-dir", default=str(DATA_LUGARES), help="Carpeta para reportes derivados.")
    parser.add_argument("--seed", type=int, default=20260906, help="Semilla de muestra manual reproducible.")
    args = parser.parse_args()

    country = load_country_config(args.country)
    base_path = Path(args.base) if args.base else default_base_path(country)
    if not base_path.is_file():
        raise FileNotFoundError(f"No existe la base nacional: {base_path}")
    base = pd.read_csv(base_path)
    require_columns(base, {"id", "title", "category", "lat", "lon", "reviews", "departamento_final", "provincia_final"})
    if base["id"].isna().any() or base["id"].astype(str).str.strip().eq("").any():
        raise ValueError("La base contiene Place IDs nulos/vacíos; ejecutar QA antes de auditar.")
    if base["id"].duplicated().any():
        raise ValueError("La base contiene Place IDs duplicados; ejecutar QA antes de auditar.")
    if not base["category"].eq("Museo").all():
        raise ValueError("La base contiene categorías distintas de 'Museo' exacto.")

    coverage, coverage_totals = coverage_report(base, country)
    collisions = possible_collisions(base)
    sample = manual_sample(base, args.seed)
    reviews = pd.to_numeric(base["reviews"], errors="coerce")
    valid_coordinates = pd.to_numeric(base["lat"], errors="coerce").notna() & pd.to_numeric(base["lon"], errors="coerce").notna()
    summary = pd.DataFrame([
        {"metrica": "pais", "valor": country["pais"], "nota": "Configuración activa."},
        {"metrica": "museos_unicos", "valor": len(base), "nota": "Place IDs únicos y category == Museo."},
        {"metrica": "coordenadas_validas", "valor": int(valid_coordinates.sum()), "nota": "Coordenadas parseables; QA valida rangos."},
        {"metrica": "departamentos_referencia", "valor": coverage_totals["departamentos_referencia"], "nota": "Primer nivel administrativo presente en geografia configurada."},
        {"metrica": "departamentos_con_museo", "valor": coverage_totals["departamentos_con_museo"], "nota": "Primer nivel con al menos un museo identificado."},
        {"metrica": "unidades_referencia", "valor": coverage_totals["unidades_referencia"], "nota": "Segundo nivel administrativo del archivo de queries."},
        {"metrica": "unidades_con_museo", "valor": coverage_totals["unidades_con_museo"], "nota": "Segundo nivel con al menos un museo identificado."},
        {"metrica": "cobertura_unidades_observada_pct", "valor": round(100 * coverage_totals["unidades_con_museo"] / coverage_totals["unidades_referencia"], 2), "nota": "No implica exhaustividad: una unidad sin museo puede ser un cero real o de descubrimiento."},
        {"metrica": "museos_con_senal_reseñas_google", "valor": int(reviews.notna().sum()), "nota": "Campo de búsqueda; no equivale a reseñas disponibles al scrapear."},
        {"metrica": "mediana_senal_reseñas_google", "valor": round(float(reviews.median()), 2), "nota": "Solo sobre valores no nulos."},
        {"metrica": "suma_senal_reseñas_google", "valor": int(reviews.fillna(0).sum()), "nota": "Estimación de búsqueda, no meta ni garantía de extracción."},
        {"metrica": "posibles_colisiones_proximas", "valor": len(collisions), "nota": "Mismo título normalizado, mismo primer nivel y distancia <= 1 km; requieren revisión manual."},
        {"metrica": "muestra_manual", "valor": len(sample), "nota": "Una fila de mayor señal y una aleatoria por primer nivel cuando existe."},
    ])

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = country["slug_pais"]
    paths = {
        "resumen": out_dir / f"auditoria_base_{slug}_resumen.csv",
        "cobertura": out_dir / f"auditoria_base_{slug}_cobertura.csv",
        "colisiones": out_dir / f"auditoria_base_{slug}_posibles_colisiones.csv",
        "muestra": out_dir / f"auditoria_base_{slug}_muestra_manual.csv",
    }
    summary.to_csv(paths["resumen"], index=False, encoding="utf-8-sig")
    coverage.to_csv(paths["cobertura"], index=False, encoding="utf-8-sig")
    collisions.to_csv(paths["colisiones"], index=False, encoding="utf-8-sig")
    sample.to_csv(paths["muestra"], index=False, encoding="utf-8-sig")

    print(summary.to_string(index=False))
    print("\nReportes derivados:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
