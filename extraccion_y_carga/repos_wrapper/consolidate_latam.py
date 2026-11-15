"""Consolida reseñas nacionales en una tabla raw plana para LATAM.

No modifica los archivos históricos por país. Lee cada CSV nacional disponible,
agrega ``pais`` y ``codigo_pais`` en memoria, deduplica globalmente por
``google_place_id + id_review`` y escribe un consolidado LATAM junto con una
tabla de progreso hacia la meta de reseñas únicas.

Uso
---
  # Consolidar todos los países configurados que ya tengan archivo nacional.
  python consolidate_latam.py

  # Validar solo Perú sin escribir archivos.
  python consolidate_latam.py --country-codes PE --dry-run
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from country_config import load_countries_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_RESENAS = PROJECT_ROOT / "data" / "resenas"
LOGS_DIR = PROJECT_ROOT / "logs"
TARGET_UNIQUE_REVIEWS = 500_000

NATIONAL_REVIEW_COLUMNS = [
    "google_place_id", "nombre_lugar", "categoria_google", "distrito", "provincia",
    "departamento", "id_review", "caption", "relative_date", "review_date",
    "retrieval_date", "rating", "username", "n_review_user", "url_user", "url_source",
]
LATAM_REVIEW_COLUMNS = ["pais", "codigo_pais", *NATIONAL_REVIEW_COLUMNS]
PROGRESS_COLUMNS = [
    "codigo_pais", "pais", "archivo_resenas_disponible", "estado_scraping_disponible",
    "resenas_unicas", "museos_con_resenas", "museos_completados", "museos_fallidos",
]


def national_review_path(country: pd.Series) -> Path:
    if country["codigo_pais"] == "PE":
        return DATA_RESENAS / "resenas_museos_consolidadas.csv"
    return DATA_RESENAS / f"resenas_museos_consolidadas_{country['slug_pais']}.csv"


def national_state_path(country: pd.Series) -> Path:
    if country["codigo_pais"] == "PE":
        return LOGS_DIR / "estado_scraping_museos.db"
    return LOGS_DIR / f"estado_scraping_museos_{country['codigo_pais'].lower()}.db"


def state_metrics(db_path: Path) -> tuple[bool, int, int]:
    """Lee el estado nacional sin modificar SQLite; devuelve disponible, OK y fallidos."""
    if not db_path.is_file():
        return False, 0, 0
    try:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT status, COUNT(*) FROM museos GROUP BY status"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return False, 0, 0
    counts = dict(rows)
    return True, int(counts.get("completado", 0)), int(counts.get("fallido", 0))


def load_national_reviews(country: pd.Series) -> pd.DataFrame | None:
    """Carga y valida un CSV nacional, sin alterar sus columnas ni filas."""
    path = national_review_path(country)
    if not path.is_file():
        return None
    reviews = pd.read_csv(path)
    missing = set(NATIONAL_REVIEW_COLUMNS) - set(reviews.columns)
    if missing:
        raise ValueError(
            f"{path.name} no cumple el contrato de reseñas; faltan columnas: "
            + ", ".join(sorted(missing))
        )
    reviews = reviews[NATIONAL_REVIEW_COLUMNS].copy()
    reviews.insert(0, "codigo_pais", country["codigo_pais"])
    reviews.insert(0, "pais", country["pais"])
    return reviews


def select_countries(config: pd.DataFrame, codes: str | None) -> pd.DataFrame:
    if not codes:
        return config.copy()
    selected_codes = [code.strip().upper() for code in codes.split(",") if code.strip()]
    unknown = sorted(set(selected_codes) - set(config["codigo_pais"].str.upper()))
    if unknown:
        raise ValueError("Códigos no configurados: " + ", ".join(unknown))
    return config[config["codigo_pais"].str.upper().isin(selected_codes)].copy()


def consolidate(countries: pd.DataFrame, target: int) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    national_frames: list[pd.DataFrame] = []
    progress_rows: list[dict] = []
    invalid_key_rows = 0

    for _, country in countries.iterrows():
        reviews = load_national_reviews(country)
        state_available, completed, failed = state_metrics(national_state_path(country))

        if reviews is None:
            unique_reviews = pd.DataFrame(columns=LATAM_REVIEW_COLUMNS)
        else:
            valid_key = (
                reviews["google_place_id"].notna()
                & reviews["id_review"].notna()
                & reviews["google_place_id"].astype(str).str.strip().ne("")
                & reviews["id_review"].astype(str).str.strip().ne("")
            )
            invalid_key_rows += int((~valid_key).sum())
            unique_reviews = reviews.loc[valid_key].drop_duplicates(
                subset=["google_place_id", "id_review"]
            )
            national_frames.append(unique_reviews)

        progress_rows.append({
            "codigo_pais": country["codigo_pais"],
            "pais": country["pais"],
            "archivo_resenas_disponible": reviews is not None,
            "estado_scraping_disponible": state_available,
            "resenas_unicas": len(unique_reviews),
            "museos_con_resenas": int(unique_reviews["google_place_id"].nunique()),
            "museos_completados": completed,
            "museos_fallidos": failed,
        })

    if national_frames:
        latam = pd.concat(national_frames, ignore_index=True)
        latam = latam.drop_duplicates(subset=["google_place_id", "id_review"])
    else:
        latam = pd.DataFrame(columns=LATAM_REVIEW_COLUMNS)
    progress = pd.DataFrame(progress_rows, columns=PROGRESS_COLUMNS)
    return latam[LATAM_REVIEW_COLUMNS], progress, invalid_key_rows


def write_outputs(latam: pd.DataFrame, progress: pd.DataFrame, out_base: Path, progress_out: Path) -> None:
    out_base.parent.mkdir(parents=True, exist_ok=True)
    latam.to_csv(out_base.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    # Un archivo Parquet plano se puede sobrescribir de forma segura en Windows
    # y OneDrive. Evitamos una carpeta particionada, porque los placeholders de
    # sincronización pueden quedar bloqueados y hacer que una reejecución no sea
    # idempotente.
    parquet_out = out_base.with_name(f"{out_base.name}_flat.parquet")
    try:
        latam.to_parquet(parquet_out, index=False)
    except (ImportError, ModuleNotFoundError):
        print("Parquet LATAM omitido: falta pyarrow o fastparquet.")
    progress_out.parent.mkdir(parents=True, exist_ok=True)
    progress.to_csv(progress_out, index=False, encoding="utf-8-sig")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--country-codes", default=None,
                        help="Códigos ISO separados por coma; default: todos los configurados.")
    parser.add_argument("--target", type=int, default=TARGET_UNIQUE_REVIEWS)
    parser.add_argument("--out", default=str(DATA_RESENAS / "resenas_museos_latam_consolidadas"),
                        help="Ruta base sin extensión para el consolidado LATAM.")
    parser.add_argument("--progress-out", default=str(DATA_RESENAS / "progreso_resenas_latam.csv"))
    parser.add_argument("--dry-run", action="store_true", help="Calcula métricas sin escribir archivos.")
    args = parser.parse_args()

    if args.target <= 0:
        parser.error("--target debe ser mayor que cero.")

    countries = select_countries(load_countries_config(), args.country_codes)
    latam, progress, invalid_key_rows = consolidate(countries, args.target)
    total = len(latam)
    remaining = max(args.target - total, 0)
    percent = total / args.target * 100

    print(f"Reseñas únicas acumuladas: {total:,}")
    print(f"Faltantes para {args.target:,}: {remaining:,}")
    print(f"Avance: {percent:.2f}%")
    print(f"Filas descartadas sin clave inequívoca: {invalid_key_rows:,}")
    print(progress.to_string(index=False))

    if args.dry_run:
        print("Dry run: no se escribieron archivos.")
        return

    write_outputs(latam, progress, Path(args.out), Path(args.progress_out))
    print(f"Consolidado LATAM -> {Path(args.out).with_suffix('.csv')}")
    print(f"Parquet LATAM -> {Path(args.out).with_name(f'{Path(args.out).name}_flat.parquet')}")
    print(f"Progreso por país -> {args.progress_out}")


if __name__ == "__main__":
    main()
