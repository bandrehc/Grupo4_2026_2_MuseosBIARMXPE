r"""Valida el contrato de lugares, reseñas y consolidado LATAM.

No modifica datos de lugares, reseñas ni checkpoints. Por defecto revisa todos
los países configurados que tengan artefactos nacionales y el consolidado LATAM
si existe. Un país aún no iniciado se informa como ``SKIP`` y no causa FAIL.

Ejemplos (PowerShell)
----------------------
  python repos_wrapper\validar_latam.py
  python repos_wrapper\validar_latam.py --country-codes MX --base-museos data\lugares\base_museos_mexico_piloto.csv --reviews data\resenas\resenas_museos_consolidadas_mexico_piloto.csv --db logs\estado_scraping_museos_mx_piloto.db --no-latam
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from consolidate_latam import LATAM_REVIEW_COLUMNS, NATIONAL_REVIEW_COLUMNS, national_review_path, national_state_path
from country_config import load_countries_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_LUGARES = PROJECT_ROOT / "data" / "lugares"
DATA_RESENAS = PROJECT_ROOT / "data" / "resenas"

REQUIRED_BASE_COLUMNS = {
    "id", "url_place", "title", "category", "lat", "lon",
    "distrito_final", "provincia_final", "departamento_final",
}
VALID_STATUSES = {"pendiente", "en_progreso", "completado", "fallido"}


class Results:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, scope: str, severity: str, check: str, count: int, detail: str) -> None:
        self.rows.append({"scope": scope, "severity": severity, "check": check, "count": count, "detail": detail})

    def error(self, scope: str, check: str, count: int, detail: str) -> None:
        self.add(scope, "FAIL", check, count, detail)

    def warn(self, scope: str, check: str, count: int, detail: str) -> None:
        self.add(scope, "WARN", check, count, detail)

    def ok(self, scope: str, check: str, count: int, detail: str) -> None:
        self.add(scope, "PASS", check, count, detail)

    def skip(self, scope: str, check: str, detail: str) -> None:
        self.add(scope, "SKIP", check, 0, detail)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=["scope", "severity", "check", "count", "detail"])

    @property
    def failed(self) -> bool:
        return any(row["severity"] == "FAIL" for row in self.rows)


def nonempty(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


def selected_countries(config: pd.DataFrame, requested: str | None) -> pd.DataFrame:
    if not requested:
        return config.copy()
    codes = {code.strip().upper() for code in requested.split(",") if code.strip()}
    unknown = sorted(codes - set(config["codigo_pais"].str.upper()))
    if unknown:
        raise ValueError("Códigos no configurados: " + ", ".join(unknown))
    return config[config["codigo_pais"].str.upper().isin(codes)].copy()


def default_base_path(country: pd.Series) -> Path:
    return DATA_LUGARES / f"base_museos_{country['slug_pais']}.csv"


def validate_base(path: Path, scope: str, result: Results) -> pd.DataFrame | None:
    if not path.is_file():
        result.skip(scope, "base_museos", f"No existe {path.name}; país aún no procesado o piloto con ruta explícita.")
        return None
    try:
        base = pd.read_csv(path)
    except Exception as exc:
        result.error(scope, "lectura_base", 1, f"No se pudo leer {path.name}: {exc}")
        return None
    missing = REQUIRED_BASE_COLUMNS - set(base.columns)
    if missing:
        result.error(scope, "schema_base", len(missing), "Columnas faltantes: " + ", ".join(sorted(missing)))
        return None
    result.ok(scope, "schema_base", len(base), f"{path.name}: columnas requeridas presentes.")
    invalid_id = ~nonempty(base["id"])
    duplicate_id = base["id"].duplicated(keep=False) & ~invalid_id
    not_museum = base["category"].fillna("").ne("Museo")
    missing_url = ~nonempty(base["url_place"])
    latitude = pd.to_numeric(base["lat"], errors="coerce")
    longitude = pd.to_numeric(base["lon"], errors="coerce")
    bad_coordinates = latitude.isna() | longitude.isna() | ~latitude.between(-90, 90) | ~longitude.between(-180, 180)
    for check, mask, description in [
        ("id_no_nulo", invalid_id, "Place ID nulo o vacío"),
        ("id_unico", duplicate_id, "Place ID duplicado"),
        ("solo_categoria_museo", not_museum, "category distinta de Museo exacto"),
        ("url_place", missing_url, "url_place nula o vacía"),
        ("coordenadas", bad_coordinates, "lat/lon nulas o fuera de rango"),
    ]:
        count = int(mask.sum())
        (result.error if count else result.ok)(scope, check, count or len(base), description if count else "OK")

    # El tercer nivel puede no existir en algunos países. Si no hubo cruce espacial,
    # debe quedar explícitamente señalado por la bandera histórica del pipeline.
    if "distrito_no_encontrado_en_poligonos" in base.columns:
        no_geo = ~nonempty(base["departamento_final"])
        unexplained = no_geo & ~base["distrito_no_encontrado_en_poligonos"].fillna(False).astype(bool)
        count = int(unexplained.sum())
        (result.warn if count else result.ok)(scope, "geografia_final", count or len(base), "Sin departamento_final ni bandera de no-encontrado" if count else "Geografía final o bandera de excepción presente.")
    return base


def validate_reviews(path: Path, scope: str, result: Results, base: pd.DataFrame | None) -> pd.DataFrame | None:
    if not path.is_file():
        result.skip(scope, "resenas_nacionales", f"No existe {path.name}; no hay reseñas nacionales consolidadas todavía.")
        return None
    try:
        reviews = pd.read_csv(path)
    except Exception as exc:
        result.error(scope, "lectura_resenas", 1, f"No se pudo leer {path.name}: {exc}")
        return None
    missing = set(NATIONAL_REVIEW_COLUMNS) - set(reviews.columns)
    if missing:
        result.error(scope, "schema_resenas", len(missing), "Columnas faltantes: " + ", ".join(sorted(missing)))
        return None
    result.ok(scope, "schema_resenas", len(reviews), f"{path.name}: contrato nacional de 16 columnas presente.")
    valid_key = nonempty(reviews["google_place_id"]) & nonempty(reviews["id_review"])
    duplicates = reviews.loc[valid_key].duplicated(["google_place_id", "id_review"], keep=False)
    invalid_category = reviews["categoria_google"].fillna("").ne("Museo")
    rating = pd.to_numeric(reviews["rating"], errors="coerce")
    bad_rating = nonempty(reviews["rating"]) & (~rating.between(1, 5))
    for check, mask, description in [
        ("clave_resena", ~valid_key, "google_place_id o id_review nulo/vacío"),
        ("deduplicacion_resena", duplicates, "Duplicado por google_place_id + id_review"),
        ("resena_de_museo", invalid_category, "categoria_google distinta de Museo exacto"),
        ("rating", bad_rating, "rating fuera del rango 1..5"),
    ]:
        count = int(mask.sum())
        (result.error if count else result.ok)(scope, check, count or len(reviews), description if count else "OK")
    for field in ["review_date", "retrieval_date"]:
        populated = nonempty(reviews[field])
        invalid_date = populated & pd.to_datetime(reviews[field], errors="coerce", utc=True).isna()
        count = int(invalid_date.sum())
        (result.error if count else result.ok)(scope, f"fecha_{field}", count or int(populated.sum()), f"{field} no parseable" if count else "Fechas pobladas parseables.")
    if base is not None:
        outside_base = valid_key & ~reviews["google_place_id"].isin(set(base["id"].dropna().astype(str)))
        count = int(outside_base.sum())
        (result.error if count else result.ok)(scope, "join_museos", count or len(reviews), "Reseña cuyo Place ID no está en base_museos." if count else "Todos los Place IDs están en base_museos.")
    return reviews


def validate_state(path: Path, scope: str, result: Results) -> None:
    if not path.is_file():
        result.skip(scope, "estado_sqlite", f"No existe {path.name}.")
        return
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            state = pd.read_sql_query("SELECT status, n_reviews_obtenidas FROM museos", connection)
        finally:
            connection.close()
    except Exception as exc:
        result.error(scope, "estado_sqlite", 1, f"No se pudo leer {path.name}: {exc}")
        return
    invalid_status = ~state["status"].isin(VALID_STATUSES)
    suspicious_zero = state["status"].eq("completado") & pd.to_numeric(state["n_reviews_obtenidas"], errors="coerce").fillna(0).eq(0)
    count = int(invalid_status.sum())
    (result.error if count else result.ok)(scope, "estado_valido", count or len(state), "Estado fuera del contrato" if count else "Estados SQLite válidos.")
    count = int(suspicious_zero.sum())
    (result.warn if count else result.ok)(scope, "completados_cero_resenas", count or len(state), "Completados con 0 reseñas: revisar posible bloqueo." if count else "Sin completados con 0 reseñas.")


def validate_latam(path: Path, config: pd.DataFrame, result: Results) -> None:
    scope = "LATAM"
    if not path.is_file():
        result.skip(scope, "consolidado_latam", f"No existe {path.name}.")
        return
    try:
        latam = pd.read_csv(path)
    except Exception as exc:
        result.error(scope, "lectura_consolidado", 1, f"No se pudo leer {path.name}: {exc}")
        return
    missing = set(LATAM_REVIEW_COLUMNS) - set(latam.columns)
    if missing:
        result.error(scope, "schema_consolidado", len(missing), "Columnas faltantes: " + ", ".join(sorted(missing)))
        return
    result.ok(scope, "schema_consolidado", len(latam), f"{path.name}: contrato LATAM de 18 columnas presente.")
    valid_key = nonempty(latam["google_place_id"]) & nonempty(latam["id_review"])
    duplicates = latam.loc[valid_key].duplicated(["google_place_id", "id_review"], keep=False)
    configured = set(config["codigo_pais"].str.upper())
    invalid_country = ~nonempty(latam["pais"]) | ~latam["codigo_pais"].astype(str).str.upper().isin(configured)
    expected_name = config.set_index("codigo_pais")["pais"].to_dict()
    mismatch_name = ~invalid_country & latam.apply(lambda row: row["pais"] != expected_name[row["codigo_pais"].upper()], axis=1)
    for check, mask, description in [
        ("clave_global", ~valid_key, "Clave global nula/vacía"),
        ("deduplicacion_global", duplicates, "Duplicado global por Place ID + review ID"),
        ("pais_codigo", invalid_country, "pais o codigo_pais no configurado"),
        ("pais_codigo_consistente", mismatch_name, "Nombre de país no coincide con su código"),
    ]:
        count = int(mask.sum())
        (result.error if count else result.ok)(scope, check, count or len(latam), description if count else "OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--country-codes", default=None, help="Códigos ISO separados por coma; default: todos.")
    parser.add_argument("--base-museos", default=None, help="Override de base para un único país (útil en pilotos).")
    parser.add_argument("--reviews", default=None, help="Override de reseñas nacionales para un único país (útil en pilotos).")
    parser.add_argument("--db", default=None, help="Override de SQLite para un único país (útil en pilotos).")
    parser.add_argument("--latam-csv", default=str(DATA_RESENAS / "resenas_museos_latam_consolidadas.csv"))
    parser.add_argument("--no-latam", action="store_true", help="Omite el chequeo del consolidado LATAM.")
    parser.add_argument("--out", default=str(DATA_RESENAS / "qa_latam_report.csv"), help="CSV de resultados de QA.")
    parser.add_argument("--dry-run", action="store_true", help="Muestra resultados sin escribir el reporte.")
    args = parser.parse_args()

    config = load_countries_config()
    countries = selected_countries(config, args.country_codes)
    if any(value is not None for value in [args.base_museos, args.reviews, args.db]) and len(countries) != 1:
        parser.error("Los overrides --base-museos/--reviews/--db requieren exactamente un país en --country-codes.")

    result = Results()
    for _, country in countries.iterrows():
        scope = f"{country['codigo_pais']} ({country['pais']})"
        base_path = Path(args.base_museos) if args.base_museos else default_base_path(country)
        review_path = Path(args.reviews) if args.reviews else national_review_path(country)
        db_path = Path(args.db) if args.db else national_state_path(country)
        base = validate_base(base_path, scope, result)
        validate_reviews(review_path, scope, result, base)
        validate_state(db_path, scope, result)

    if not args.no_latam:
        validate_latam(Path(args.latam_csv), config, result)

    report = result.frame()
    print(report.to_string(index=False))
    print("FAIL" if result.failed else "PASS")
    if args.dry_run:
        print("Dry run: no se escribió reporte.")
    else:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        report.to_csv(output, index=False, encoding="utf-8-sig")
        print(f"Reporte QA -> {output}")
    if result.failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
