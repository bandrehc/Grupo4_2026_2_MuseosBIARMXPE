"""Crea una muestra reproducible de museos para un piloto de reseñas.

Estrategia actual: por cada unidad de primer nivel administrativo se selecciona
un museo con la mayor señal ``reviews`` de discovery y otro museo aleatorio.
La columna ``reviews`` se usa solo para estratificar; no representa una cuota
de reseñas extraíbles.
"""
import argparse
from pathlib import Path

import pandas as pd

from country_config import load_country_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_LUGARES = PROJECT_ROOT / "data" / "lugares"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", default="MX")
    parser.add_argument("--base", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--seed", type=int, default=20260906)
    parser.add_argument("--top-reviews", type=int, default=None,
                        help="Selecciona los N museos con mayor señal reviews; útil para estrés de alto volumen.")
    args = parser.parse_args()

    country = load_country_config(args.country)
    slug = country["slug_pais"]
    base_path = Path(args.base) if args.base else DATA_LUGARES / f"base_museos_{slug}.csv"
    out_path = Path(args.out) if args.out else DATA_LUGARES / f"base_museos_{slug}_piloto_ampliado.csv"
    manifest_path = Path(args.manifest) if args.manifest else DATA_LUGARES / f"piloto_museos_{slug}_manifest.csv"
    base = pd.read_csv(base_path)
    required = {"id", "category", "reviews", "departamento_final"}
    missing = sorted(required - set(base.columns))
    if missing:
        raise ValueError("Faltan columnas: " + ", ".join(missing))
    if not base["category"].eq("Museo").all():
        raise ValueError("El piloto exige una base con category == 'Museo' exacto.")
    if base["id"].duplicated().any():
        raise ValueError("El piloto exige Place IDs únicos.")

    work = base.copy()
    work["_reviews_numeric"] = pd.to_numeric(work["reviews"], errors="coerce").fillna(-1)
    if args.top_reviews is not None:
        if args.top_reviews <= 0:
            raise ValueError("--top-reviews debe ser positivo.")
        pilot = work.sort_values(["_reviews_numeric", "id"], ascending=[False, True]).head(args.top_reviews).copy()
        pilot["motivo_piloto"] = "mayor_senal_reseñas_google"
        pilot = pilot.drop(columns=["_reviews_numeric"])
    else:
        selected: list[pd.DataFrame] = []
        for department, group in work.groupby("departamento_final", dropna=False, sort=True):
            if pd.isna(department) or not str(department).strip():
                raise ValueError("La base contiene museo sin departamento_final; corregir antes del piloto estratificado.")
            top = group.sort_values(["_reviews_numeric", "id"], ascending=[False, True]).head(1).copy()
            top["motivo_piloto"] = "mayor_senal_reseñas_google"
            selected.append(top)
            remaining = group.loc[~group["id"].isin(top["id"])].copy()
            if not remaining.empty:
                random_row = remaining.sample(n=1, random_state=args.seed).copy()
                random_row["motivo_piloto"] = "aleatoria_estratificada"
                selected.append(random_row)
        pilot = pd.concat(selected, ignore_index=True).drop(columns=["_reviews_numeric"])
    if pilot["id"].duplicated().any():
        raise AssertionError("La selección produjo Place IDs duplicados.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pilot.to_csv(out_path, index=False, encoding="utf-8-sig")
    manifest = pilot[["id", "title", "departamento_final", "provincia_final", "reviews", "motivo_piloto"]].copy()
    manifest.to_csv(manifest_path, index=False, encoding="utf-8-sig")
    print(f"Piloto {country['pais']}: {len(pilot)} museos en {pilot['departamento_final'].nunique()} unidades de primer nivel.")
    print(f"Base piloto: {out_path}")
    print(f"Manifiesto: {manifest_path}")


if __name__ == "__main__":
    main()
