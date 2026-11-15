"""Prepara los tres insumos geográficos de México requeridos por el pipeline.

Fuente: geoBoundaries gbOpen (CC BY 4.0), revisión 9469f09. Descarga ADM0,
ADM1 y ADM2 simplificados; asigna cada municipio a su estado mediante un punto
representativo y escribe únicamente los artefactos normalizados que consume el
proyecto. Se usa la variante simplificada para no añadir geometrías gigantes.

Uso:
    python prepare_mexico_geography.py
"""
import io
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import geopandas as gpd
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REF_DIR = PROJECT_ROOT / "data" / "referencia"
REVISION = "9469f09"
BASE_URL = f"https://github.com/wmgeolab/geoBoundaries/raw/{REVISION}/releaseData/gbOpen/MEX"
SOURCES = {
    "adm0": f"{BASE_URL}/ADM0/geoBoundaries-MEX-ADM0_simplified.geojson",
    "adm1": f"{BASE_URL}/ADM1/geoBoundaries-MEX-ADM1_simplified.geojson",
    "adm2": f"{BASE_URL}/ADM2/geoBoundaries-MEX-ADM2_simplified.geojson",
}
OUTPUTS = {
    "boundary": REF_DIR / "mexico_boundary.geojson",
    "divisions": REF_DIR / "mexico_divisiones.geojson",
    "units": REF_DIR / "geografia_mexico.csv",
}


def download_geodataframe(url: str) -> gpd.GeoDataFrame:
    print(f"Descargando {url.rsplit('/', 1)[-1]}...", flush=True)
    request = Request(url, headers={"User-Agent": "museos-de-america-etl/1.0"})
    with urlopen(request, timeout=90) as response:
        content = response.read()
    frame = gpd.read_file(io.BytesIO(content))
    if frame.empty:
        raise ValueError(f"La fuente no contiene geometrías: {url}")
    if frame.crs is None:
        frame = frame.set_crs("EPSG:4326")
    return frame.to_crs("EPSG:4326")


def required_column(frame: gpd.GeoDataFrame, name: str, source_name: str) -> str:
    if name not in frame.columns:
        raise ValueError(f"{source_name} no contiene la propiedad requerida {name!r}: {list(frame.columns)}")
    return name


def prepare() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, pd.DataFrame]:
    boundary = download_geodataframe(SOURCES["adm0"])
    states = download_geodataframe(SOURCES["adm1"])
    municipalities = download_geodataframe(SOURCES["adm2"])

    state_name = required_column(states, "shapeName", "ADM1")
    municipality_name = required_column(municipalities, "shapeName", "ADM2")
    municipality_id = required_column(municipalities, "shapeID", "ADM2")

    state_lookup = states[[state_name, "geometry"]].rename(columns={state_name: "departamento"}).copy()
    representative_points = municipalities[[municipality_name, municipality_id]].copy()
    representative_points["geometry"] = municipalities.geometry.representative_point()
    representative_points = gpd.GeoDataFrame(representative_points, geometry="geometry", crs="EPSG:4326")
    joined = gpd.sjoin(representative_points, state_lookup, how="left", predicate="within")
    joined["origen_departamento"] = "within_adm1_simplificado"
    missing_mask = joined["departamento"].isna()
    if missing_mask.any():
        # Algunas islas o bordes se pierden al simplificar ADM1. El nombre se
        # toma del polígono ADM1 más cercano de la misma fuente y queda marcado
        # para auditoría, en lugar de inventar una equivalencia administrativa.
        missing_points = joined.loc[missing_mask, [municipality_name, municipality_id, "geometry"]].to_crs("EPSG:3857")
        nearest = gpd.sjoin_nearest(
            missing_points,
            state_lookup.to_crs("EPSG:3857"),
            how="left",
            distance_col="distancia_adm1_metros",
        ).sort_values("distancia_adm1_metros").drop_duplicates(subset=[municipality_id], keep="first")
        if nearest["departamento"].isna().any():
            raise ValueError("No se pudo asignar estado a todos los municipios fuera de ADM1 simplificado.")
        nearest_by_id = nearest.set_index(municipality_id)
        joined.loc[missing_mask, "departamento"] = joined.loc[missing_mask, municipality_id].map(nearest_by_id["departamento"])
        joined.loc[missing_mask, "origen_departamento"] = "nearest_adm1_simplificado"

    divisions = municipalities.copy()
    divisions["codigo_unidad"] = municipalities[municipality_id].astype(str)
    divisions["departamento"] = joined["departamento"].values
    divisions["provincia"] = municipalities[municipality_name].astype(str)
    divisions["distrito"] = ""
    divisions["origen_departamento"] = joined["origen_departamento"].values
    divisions = divisions[["codigo_unidad", "departamento", "provincia", "distrito", "origen_departamento", "geometry"]]

    units = divisions.drop(columns="geometry").drop_duplicates(subset=["codigo_unidad"]).copy()
    if units["codigo_unidad"].duplicated().any():
        raise ValueError("El identificador de municipio no es único tras la normalización.")
    return boundary, divisions, units


def main() -> None:
    existing = [path for path in OUTPUTS.values() if path.exists()]
    if existing:
        sys.exit(
            "No se sobrescriben referencias existentes. Elimine o mueva explícitamente: "
            + ", ".join(str(path) for path in existing)
        )

    boundary, divisions, units = prepare()
    REF_DIR.mkdir(parents=True, exist_ok=True)
    boundary.to_file(OUTPUTS["boundary"], driver="GeoJSON")
    divisions.to_file(OUTPUTS["divisions"], driver="GeoJSON")
    units.to_csv(OUTPUTS["units"], index=False, encoding="utf-8")
    print(f"ADM0: {len(boundary)} geometría(s) -> {OUTPUTS['boundary'].name}")
    print(f"ADM2: {len(divisions)} municipios -> {OUTPUTS['divisions'].name}")
    print(f"Queries: {len(units)} unidades -> {OUTPUTS['units'].name}")


if __name__ == "__main__":
    main()
