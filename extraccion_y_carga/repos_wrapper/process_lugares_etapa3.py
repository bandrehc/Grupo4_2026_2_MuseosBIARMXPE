"""process_lugares_etapa3.py — Depuración y validación geográfica por país.

Toma lugares candidatos de un país (salida cruda de la Etapa 2) y produce:
  - lugares_identificados_<pais>.parquet / .csv
  - lugares_descartados_<pais>.csv
  - base_museos_<pais>.csv, filtrada con ``category == "Museo"`` exacto
  - un resumen estadístico impreso en consola (y guardado en logs/)

Pasos
-----
1. Deduplicación por `id` de Google, priorizando el registro de nivel de query
   más específico (distrito > provincia > departamento) cuando el mismo lugar
   aparece por colisión de texto entre niveles.
2. Filtro estricto del país: point-in-polygon contra su límite nacional configurado.
3. Cruce espacial contra sus divisiones administrativas para asignar
   distrito/provincia/departamento reales
   por coordenadas, y comparar contra el distrito que originó la query.
4. Clasificación en la taxonomía de categorias.csv combinando la categoría reportada
   por Google con coincidencia de palabra clave en el nombre, con nivel de confianza.
5. Split final en identificados (parquet+csv) vs descartados (csv, con motivo).

Uso
---
  # Compatibilidad histórica de Perú (no ejecutar durante el refactor).
  python process_lugares_etapa3.py

  # País nuevo, con rutas aisladas resueltas desde paises_latam.csv.
  python process_lugares_etapa3.py --country MX
"""
import argparse
import re
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from country_config import asset_path, load_country_config, require_geography_assets

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_REF = PROJECT_ROOT / "data" / "referencia"
DATA_LUGARES = PROJECT_ROOT / "data" / "lugares"

NIVEL_PRIORIDAD = {"distrito": 0, "provincia": 1, "departamento": 2}

# Categorias reportadas por Google que en el piloto de la Etapa 1 resultaron ser
# consistentemente ruido (negocios no patrimoniales que colaron por coincidencia de
# nombre comercial con la query, ej. hoteles llamados "Casa X").
CATEGORIAS_RUIDO_GOOGLE = {
    "hotel", "restaurante", "bar", "parque", "bed & breakfast",
    "alojamiento con servicio", "sociedad de viviendas", "zona de senderismo",
    "mirador", "town square", "parque nacional", "cafeteria", "cafetería",
    "pizzeria", "pizzería", "night club", "discoteca", "supermercado",
    "farmacia", "banco", "gimnasio", "peluqueria", "peluquería",
}

# Patrones (substring, sobre texto normalizado) de categorias de Google que son
# ruido GENUINO — a diferencia de CATEGORIAS_RUIDO_GOOGLE (que permite "baja
# confianza" si hay coincidencia de palabra clave en el nombre), estas fuerzan
# "descartar" siempre, incluso con coincidencia de palabra clave, porque son
# categorias que casi nunca corresponden a un sitio patrimonial real (oficinas,
# inmobiliarias, negocios genericos, colegios, etc. que colaron solo porque su
# nombre comercial contiene una palabra clave, ej. "Urbanizacion Ciudadela Real").
# Construido revisando manualmente las ~350 categorias distintas presentes en
# data/lugares/lugares_identificados.csv.
RUIDO_GENUINO_PATTERNS = [
    # vivienda / inmobiliario
    "urbanizacion", "condominio", "complejo de apartamento", "edificio de apartamento",
    "cooperativa de vivienda", "complejo de vivienda", "sociedad de vivienda",
    "zona residencial", "housing complex", "agencia inmobiliaria",
    "agencia de bienes inmuebles", "promotora inmobiliaria", "agentes inmobiliarios",
    "inmobiliaria", "consultor inmobiliario", "tasador de bienes inmuebles",
    "propiedad de arrendatario", "distribucion de tierras",
    "departamento local de ocupacion", "programa de vivienda",
    "comunidad para jubilados", "residencia de ancianos", "residencia geriatrica",
    "holiday apartment", "holiday home", "departamento municipal",
    # gobierno / administracion / seguridad / justicia
    "diputacion", "oficina del gobierno", "oficina de la administracion",
    "oficina de gobierno local", "ayuntamiento", "junta municipal",
    "oficina de administracion municipal", "secretaria municipal",
    "oficina tributaria municipal", "delegacion regional del gobierno",
    "fiscal de distrito", "departamento de seguridad publica",
    "departamento de asuntos de veteranos", "comisaria de policia",
    "jefatura de policia", "policia nacional", "policia federal",
    "oficina de seguridad publica", "oficina de atencion al ciudadano",
    "oficina del censo electoral", "registro civil", "camara de comercio",
    "juzgado", "oficina de abogado defensor", "sala municipal",
    "departamento de obras publicas", "departamento de planificacion urbanistica",
    "departamento de salud publica", "centro penitenciario",
    "centro de detencion de menores", "patrulla fronteriza", "puesto fronterizo",
    "cuarteles militares", "base naval", "aeropuerto militar",
    # negocios / empresas / servicios genericos
    "oficinas de empresa", "empresa constructora", "empresa minera",
    "empresa de medios", "empresa de organizacion de eventos",
    "empresa de construccion", "empresa de software", "empresa de transporte",
    "empresa portuaria", "empresa ferroviaria", "servicio de ", "mayorista",
    "constructor", "estudio de arquitectura", "arquitecto", "centro de negocios",
    "centro comercial", "grandes almacenes", "hipermercado", "espacio de coworking",
    "asesor", "agencia de seguros", "agencia de publicidad", "agencia de viajes",
    "agencia de excursiones", "agencia de alquiler", "tienda de ", "ferreteria",
    "farmacia", "zapateria", "joyeria", "libreria", "optica", "cibercafe",
    # educacion generica (no patrimonial)
    "institucion educativa", "centro educativo", "instituto de secundaria",
    "universidad", "jardin de infancia", "escuela universitaria", "colegio",
    "escuela primaria", "escuela de primaria", "centro de educacion secundaria",
    "educacion mixta", "academia de ingles", "academia de idiomas",
    "instituto de tecnologia", "centro de estudios", "escuela deportiva",
    "instituto femenino", "escuela tecnica", "escuela de musica", "escuela de surf",
    # hoteleria / gastronomia generica
    "hotel", "alojamiento", "cafeteria", "restaurante", " bar", "bar ",
    "pension", "albergue", "posada", "lodge", "homestay", "panaderia",
    "heladeria", "pasteleria", "marisqueria", "parrilla", "buffet",
    "cocteleria", "taberna", "lounge", "casino", "discoteca", "club nocturno",
    "spa", "sauna", "pub",
    # recreacion / deporte no historico
    "parque local", "parque infantil", "parque tematico", "parque acuatico",
    "parque de atracciones", "parque de ciclismo", "parque tecnologico",
    "parque empresarial", "piscina", "zoo", "acuario", "estadio",
    "polideportivo", "campo de futbol", "circuito de bmx", "centro deportivo",
    "club deportivo", "club social", "club de campo", "centro de recreo",
    "centro de ocio", "salon recreativo",
    # salud
    "hospital", "centro medico", "centro de salud", "laboratorio", "medico",
    "dentista", "podologo", "morgue", "clinica",
    # transporte / infraestructura generica
    "aeropuerto", "estacion de tren", "estacion de autobuses",
    "parada de transporte", "bus stop", "aparcamiento", "peaje", "gasolinera",
    "puerto maritimo", "puerto deportivo",
    # industrial
    "cantera", "refineria", "central electrica", "fabrica", "fundicion",
    "planta depuradora", "compania suministradora de agua", "compania electrica",
]


def categoria_es_ruido_genuino(category_norm: str) -> bool:
    return any(p in category_norm for p in RUIDO_GENUINO_PATTERNS)


# Patrones (substring) de categorias de Google que son templos/edificios religiosos
# reales — senal positiva fuerte para patrimonio_religioso. Se agregaron el
# 2026-08-12 a pedido del usuario: ~300 lugares con estas categorias exactas
# habian quedado en confianza baja porque CATEGORIAS_BUENAS_GOOGLE (match exacto)
# no cubria las variantes que realmente usa Google (ej. "Iglesia adventista del
# septimo dia", "Iglesia de Jesucristo de los Santos de los Ultimos Dias").
# Deliberadamente no incluye "escuela"/"colegio" combinados con religioso (ej.
# "Escuela parroquial", "Colegio religioso", "Escuela catolica") porque esas son
# escuelas en funcionamiento, no el templo en si — quedan en confianza baja/ambigua.
CATEGORIAS_BUENAS_PATTERNS = [
    "iglesia", "parroquia", "monasterio", "convento", "capilla", "catedral",
    "basilica", "sinagoga", "mezquita", "gurudwara", "santuario",
    "lugar de culto", "destino religioso", "organizacion religiosa",
    "institucion religiosa", "congregacion", "rectoria", "seminario",
]


def categoria_es_buena_senal_religiosa(category_norm: str) -> bool:
    return any(p in category_norm for p in CATEGORIAS_BUENAS_PATTERNS)


# Categorias reportadas por Google que son senal fuerte y positiva de patrimonio.
CATEGORIAS_BUENAS_GOOGLE = {
    "museo", "museo arqueologico", "museo arqueológico", "museo de arte",
    "museo de historia", "museo de historia local", "museo de historia natural",
    "museo patrimonial", "museo de escultura", "museo de sitio",
    "yacimiento arqueologico", "yacimiento arqueológico", "zona arqueologica",
    "zona arqueológica", "lugar de interes historico", "lugar de interés histórico",
    "monumento", "lugar historico", "lugar histórico", "centro cultural",
    "santuario historico", "santuario histórico", "sitio historico",
    "sitio histórico", "monumento historico", "monumento histórico",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))


def _norm(s: str) -> str:
    return _strip_accents(str(s)).lower().strip()


def load_categorias() -> pd.DataFrame:
    return pd.read_csv(DATA_REF / "categorias.csv")


def build_keyword_roots(categorias: pd.DataFrame) -> dict:
    """Palabra clave -> raiz corta usable para matching por substring (singular y plural)."""
    roots = {}
    for _, row in categorias.iterrows():
        cat = row["categoria_normalizada"]
        for palabra in (row["palabra_clave"], row["termino_busqueda_plural"]):
            for tok in _norm(palabra).split():
                if len(tok) >= 5 and tok not in {"museo", "museos"}:
                    roots.setdefault(tok[:-1] if tok.endswith("s") else tok, cat)
        # palabra clave completa tambien (para frases como "sitio de interes historico")
        roots[_norm(row["palabra_clave"])] = cat
    roots["museo"] = "museo"
    return roots


def dedup_por_id(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df["_prioridad_nivel"] = df["nivel"].map(NIVEL_PRIORIDAD).fillna(9)
    df_sorted = df.sort_values(["id", "_prioridad_nivel"])
    dedup = df_sorted.drop_duplicates(subset=["id"], keep="first").drop(columns=["_prioridad_nivel"])
    descartados_dup = df_sorted[df_sorted.duplicated(subset=["id"], keep="first")].drop(columns=["_prioridad_nivel"])
    descartados_dup = descartados_dup.assign(motivo_descarte="duplicado")
    return dedup, descartados_dup


def parse_coords(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    coords = df["coor"].astype(str).str.split(",", expand=True)
    df["lat"] = pd.to_numeric(coords[0], errors="coerce")
    df["lon"] = pd.to_numeric(coords[1], errors="coerce")
    return df


def filtro_pais(df: pd.DataFrame, country: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Conserva solo puntos dentro del límite nacional configurado."""
    boundary_path = asset_path(country, "archivo_boundary")
    boundary = gpd.read_file(boundary_path)
    country_geom = boundary.union_all()

    sin_coords = df[df["lat"].isna() | df["lon"].isna()].assign(motivo_descarte="sin_coordenadas_validas")
    con_coords = df.dropna(subset=["lat", "lon"]).copy()

    gdf = gpd.GeoDataFrame(
        con_coords, geometry=gpd.points_from_xy(con_coords["lon"], con_coords["lat"]), crs="EPSG:4326"
    )
    dentro = gdf[gdf.geometry.within(country_geom)].copy()
    fuera = gdf[~gdf.geometry.within(country_geom)].copy()
    fuera = fuera.assign(motivo_descarte=f"fuera_del_poligono_de_{country['slug_pais']}")

    fuera_df = pd.DataFrame(fuera.drop(columns="geometry"))
    sin_coords_df = pd.DataFrame(sin_coords)
    return dentro, pd.concat([fuera_df, sin_coords_df], ignore_index=True)


def cruce_divisiones(gdf: gpd.GeoDataFrame, country: pd.Series) -> gpd.GeoDataFrame:
    """Asigna niveles administrativos reales según las propiedades configuradas."""
    source_columns = {
        "inei_real": country["columna_division_id"],
        "distrito_real": country["columna_division_distrito"],
        "provincia_real": country["columna_division_provincia"],
        "departamento_real": country["columna_division_departamento"],
    }
    divisions_path = asset_path(country, "archivo_divisiones")
    divisions = gpd.read_file(divisions_path)
    missing = [column for column in source_columns.values() if column not in divisions.columns]
    if missing:
        raise ValueError(
            f"{divisions_path.name} no cumple la configuración de {country['pais']}; "
            f"faltan propiedades: {', '.join(sorted(set(missing)))}"
        )
    divisions = divisions[list(source_columns.values()) + ["geometry"]].rename(
        columns={source: target for target, source in source_columns.items()}
    )
    joined = gpd.sjoin(gdf, divisions, how="left", predicate="within")
    joined = joined.drop(columns=["index_right"], errors="ignore")
    # sjoin puede introducir duplicados de fila si un punto cae en el borde de 2
    # poligonos; nos quedamos con la primera coincidencia por id.
    joined = joined.sort_values("id").drop_duplicates(subset=["id"], keep="first")

    def _norm_series(s):
        return s.astype(str).map(_norm)

    joined["distrito_no_encontrado_en_poligonos"] = joined["distrito_real"].isna()
    joined["coincide_con_distrito_de_consulta"] = (
        _norm_series(joined["distrito_real"].fillna("")) == _norm_series(joined["distrito"].fillna(""))
    )

    def _titlecase(s):
        if pd.isna(s):
            return ""
        return " ".join(w.capitalize() for w in str(s).strip().split())

    # Si una división no cubre el punto, se usa la geografía de la query como
    # mejor estimado disponible. La bandera anterior conserva la trazabilidad.
    joined["distrito_final"] = joined["distrito_real"].fillna(joined["distrito"]).map(_titlecase)
    joined["provincia_final"] = joined["provincia_real"].fillna(joined["provincia"]).map(_titlecase)
    joined["departamento_final"] = joined["departamento_real"].fillna(joined["departamento"]).map(_titlecase)
    return joined


def default_paths(country: pd.Series) -> dict[str, Path | None]:
    """Resuelve rutas aisladas; Perú conserva sus nombres históricos."""
    suffix = "" if country["codigo_pais"] == "PE" else f"_{country['slug_pais']}"
    base_museos = None if country["codigo_pais"] == "PE" else DATA_LUGARES / f"base_museos_{country['slug_pais']}.csv"
    return {
        "input": DATA_LUGARES / f"lugares_candidatos{suffix}.csv",
        "identificados": DATA_LUGARES / f"lugares_identificados{suffix}",
        "descartados": DATA_LUGARES / f"lugares_descartados{suffix}.csv",
        "base_museos": base_museos,
    }


def clasificar(df: pd.DataFrame, keyword_roots: dict) -> pd.DataFrame:
    df = df.copy()
    title_norm = df["title"].fillna("").map(_norm)
    category_norm = df["category"].fillna("").map(_norm)

    def matches_any_keyword(t):
        return any(root in t for root in keyword_roots if len(root) >= 4)

    df["coincide_keyword_en_nombre"] = title_norm.map(matches_any_keyword)
    df["categoria_google_es_ruido_conocido"] = category_norm.isin(CATEGORIAS_RUIDO_GOOGLE)
    df["categoria_google_es_buena_senal"] = (
        category_norm.isin(CATEGORIAS_BUENAS_GOOGLE) | category_norm.map(categoria_es_buena_senal_religiosa)
    )
    df["categoria_google_es_ruido_genuino"] = category_norm.map(categoria_es_ruido_genuino)

    def confianza(row):
        if row["categoria_google_es_buena_senal"]:
            return "alta"
        # ruido genuino descarta siempre, incluso con coincidencia de palabra
        # clave (a diferencia de categoria_google_es_ruido_conocido, mas laxa).
        if row["categoria_google_es_ruido_genuino"]:
            return "descartar"
        if row["categoria_google_es_ruido_conocido"] and not row["coincide_keyword_en_nombre"]:
            return "descartar"
        if row["categoria_google_es_ruido_conocido"] and row["coincide_keyword_en_nombre"]:
            return "baja"
        if row["coincide_keyword_en_nombre"]:
            return "alta"
        return "baja"

    df["confianza_clasificacion"] = df.apply(confianza, axis=1)
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filtro-museo", choices=["exacto", "contiene"], default="exacto",
                    help="exacto: category == 'Museo' (Peru/Mexico); contiene: cualquier categoria con la palabra museo (Argentina)")
    ap.add_argument("--country", "--codigo-pais", dest="codigo_pais", default="PE",
                    help="Código ISO alpha-2 configurado en paises_latam.csv (default: PE)")
    ap.add_argument("--in", dest="input_csv", default=None,
                    help="CSV de lugares candidatos; default: ruta aislada del país")
    ap.add_argument("--out-identificados", default=None,
                    help="Ruta base sin extensión para identificados; default: ruta aislada del país")
    ap.add_argument("--out-descartados", default=None,
                    help="CSV de descartados; default: ruta aislada del país")
    ap.add_argument("--out-base-museos", default=None,
                    help="CSV final con category == 'Museo' exacto; default: ruta aislada del país nuevo")
    args = ap.parse_args()

    country = load_country_config(args.codigo_pais)
    require_geography_assets(country)
    paths = default_paths(country)
    input_csv = Path(args.input_csv) if args.input_csv else paths["input"]
    out_identificados = Path(args.out_identificados) if args.out_identificados else paths["identificados"]
    out_descartados = Path(args.out_descartados) if args.out_descartados else paths["descartados"]
    out_base_museos = Path(args.out_base_museos) if args.out_base_museos else paths["base_museos"]

    if not input_csv.is_file():
        raise FileNotFoundError(f"No existe el CSV de lugares candidatos: {input_csv}")

    print(f"Cargando {input_csv.name} para {country['pais']} ({country['codigo_pais']})...")
    df = pd.read_csv(input_csv)
    n_inicial = len(df)
    print(f"  {n_inicial} filas crudas")

    df, descartados_dup = dedup_por_id(df)
    print(f"  {len(df)} lugares unicos tras deduplicar por id ({len(descartados_dup)} duplicados removidos)")

    df = parse_coords(df)

    print(f"Aplicando filtro estricto de polígono de {country['pais']}...")
    dentro, descartados_fuera = filtro_pais(df, country)
    print(f"  {len(dentro)} dentro de {country['pais']}, {len(descartados_fuera)} descartados (fuera o sin coordenadas)")

    print("Cruzando contra divisiones administrativas configuradas...")
    dentro = cruce_divisiones(gpd.GeoDataFrame(dentro, geometry=gpd.points_from_xy(dentro["lon"], dentro["lat"]), crs="EPSG:4326"), country)
    n_no_encontrado = dentro["distrito_no_encontrado_en_poligonos"].sum()
    n_no_coincide = (~dentro["coincide_con_distrito_de_consulta"]).sum()
    print(f"  {n_no_encontrado} lugares sin división administrativa que los cubra")
    print(f"  {n_no_coincide} lugares donde la geografía real no coincide con la query que los originó")

    print("Clasificando por categoria y calculando confianza...")
    categorias = load_categorias()
    keyword_roots = build_keyword_roots(categorias)
    dentro = clasificar(dentro, keyword_roots)

    descartados_ruido = dentro[dentro["confianza_clasificacion"] == "descartar"].copy()
    descartados_ruido["motivo_descarte"] = descartados_ruido["categoria_google_es_ruido_genuino"].map(
        lambda es_ruido_genuino: "ruido_genuino_categoria_google" if es_ruido_genuino else "no_cumple_ninguna_categoria"
    )
    identificados = dentro[dentro["confianza_clasificacion"] != "descartar"].copy()

    n_ruido_genuino = (descartados_ruido["motivo_descarte"] == "ruido_genuino_categoria_google").sum()
    print(f"  {len(identificados)} identificados ({(identificados['confianza_clasificacion']=='alta').sum()} alta confianza, {(identificados['confianza_clasificacion']=='baja').sum()} baja confianza)")
    print(f"  {len(descartados_ruido)} descartados por categoria (de los cuales {n_ruido_genuino} por ruido genuino explicito, {len(descartados_ruido)-n_ruido_genuino} por no coincidir con ninguna palabra clave)")

    identificados = identificados.drop(columns=["geometry"], errors="ignore")
    descartados_ruido = descartados_ruido.drop(columns=["geometry"], errors="ignore")

    out_identificados.parent.mkdir(parents=True, exist_ok=True)
    identificados.to_csv(out_identificados.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    identificados.to_parquet(out_identificados.with_suffix(".parquet"), index=False)

    descartados_final = pd.concat([
        descartados_dup, descartados_fuera, descartados_ruido,
    ], ignore_index=True)
    out_descartados.parent.mkdir(parents=True, exist_ok=True)
    descartados_final.to_csv(out_descartados, index=False, encoding="utf-8-sig")

    if out_base_museos:
        out_base_museos.parent.mkdir(parents=True, exist_ok=True)
        if args.filtro_museo == "contiene":
            # Universo ampliado: toda categoria de Google que mencione "museo", tomada
            # ANTES del filtro de ruido para no perder museos por la heuristica de palabras clave.
            todos = pd.concat([identificados, descartados_ruido], ignore_index=True)
            base_museos = todos[todos["category"].fillna("").map(_norm).str.contains("museo", regex=False)].copy()
            base_museos = base_museos.drop(columns=["geometry"], errors="ignore")
            etiqueta = "museos (categoria contiene 'museo')"
        else:
            base_museos = identificados[identificados["category"].eq("Museo")].copy()
            etiqueta = "museos exactos"
        base_museos.to_csv(out_base_museos, index=False, encoding="utf-8-sig")
        print(f"  {len(base_museos)} {etiqueta} -> {out_base_museos}")
    elif country["codigo_pais"] == "PE":
        print("  Perú: no se regenera base_museos_peru.csv sin --out-base-museos explícito.")

    print()
    print("=== RESUMEN ===")
    print(f"Total crudo (Etapa 2):              {n_inicial}")
    print(f"Duplicados removidos:                {len(descartados_dup)}")
    print(f"Fuera de {country['pais']} / sin coordenadas:     {len(descartados_fuera)}")
    print(f"Descartados por categoria (ruido):   {len(descartados_ruido)}")
    print(f"LUGARES IDENTIFICADOS (final):        {len(identificados)}")
    print(f"  - confianza alta: {(identificados['confianza_clasificacion']=='alta').sum()}")
    print(f"  - confianza baja: {(identificados['confianza_clasificacion']=='baja').sum()}")
    print()
    print("Por categoria normalizada:")
    print(identificados["categoria_normalizada"].value_counts().to_string())
    print()
    print("Por departamento:")
    print(identificados["departamento_final"].value_counts().to_string())


if __name__ == "__main__":
    main()
