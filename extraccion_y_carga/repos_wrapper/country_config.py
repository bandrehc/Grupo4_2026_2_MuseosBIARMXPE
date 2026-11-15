"""Lectura y validación compartida de ``data/referencia/paises_latam.csv``.

Este módulo no crea rutas ni descarga datos. Centraliza la configuración que
usan las etapas de queries, búsqueda y validación geográfica.
"""
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REF_DIR = PROJECT_ROOT / "data" / "referencia"
COUNTRIES_CONFIG = REF_DIR / "paises_latam.csv"

CONFIG_REQUIRED_COLUMNS = {
    "codigo_pais", "pais", "slug_pais", "google_country_code", "idioma",
    "estado_geografia", "archivo_unidades_query", "archivo_boundary",
    "archivo_divisiones", "columna_unidad_id", "columna_unidad_departamento",
    "columna_unidad_provincia", "columna_unidad_distrito",
    "columna_division_id", "columna_division_departamento",
    "columna_division_provincia", "columna_division_distrito",
}


def load_countries_config() -> pd.DataFrame:
    """Carga y valida la tabla completa de configuración de países."""
    if not COUNTRIES_CONFIG.is_file():
        raise FileNotFoundError(f"No existe la configuración de países: {COUNTRIES_CONFIG}")

    config = pd.read_csv(COUNTRIES_CONFIG, dtype=str).fillna("")
    faltantes = CONFIG_REQUIRED_COLUMNS - set(config.columns)
    if faltantes:
        raise ValueError(
            "paises_latam.csv no tiene las columnas requeridas: "
            + ", ".join(sorted(faltantes))
        )
    if config["codigo_pais"].str.upper().duplicated().any():
        raise ValueError("paises_latam.csv contiene codigo_pais duplicados.")
    return config


def load_country_config(codigo_pais: str, require_enabled: bool = True) -> pd.Series:
    """Devuelve una única fila de configuración, validada y normalizada."""
    config = load_countries_config()

    code = codigo_pais.strip().upper()
    matches = config[config["codigo_pais"].str.upper().eq(code)]
    if len(matches) != 1:
        disponibles = ", ".join(config["codigo_pais"].tolist())
        raise ValueError(
            f"Código de país inválido o duplicado: {codigo_pais!r}. "
            f"Códigos configurados: {disponibles}."
        )

    country = matches.iloc[0]
    if require_enabled and country["estado_geografia"].strip().lower() != "disponible":
        raise FileNotFoundError(
            f"{country['pais']} ({country['codigo_pais']}) no está habilitado: "
            f"estado_geografia={country['estado_geografia']!r}. "
            "Falta añadir y documentar "
            f"{country['archivo_unidades_query']}, {country['archivo_boundary']} y "
            f"{country['archivo_divisiones']} antes de ejecutar el pipeline."
        )
    return country


def asset_path(country: pd.Series, config_column: str) -> Path:
    """Resuelve un archivo de referencia declarado en la configuración."""
    filename = country.get(config_column, "")
    if not filename:
        raise ValueError(
            f"La configuración de {country['pais']} no define {config_column}."
        )
    return REF_DIR / filename


def require_geography_assets(country: pd.Series, include_divisions: bool = True) -> None:
    """Comprueba que los insumos espaciales declarados existan antes de procesar."""
    config_columns = ["archivo_unidades_query", "archivo_boundary"]
    if include_divisions:
        config_columns.append("archivo_divisiones")
    missing = [str(asset_path(country, column)) for column in config_columns if not asset_path(country, column).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Faltan insumos geográficos de {country['pais']}: " + "; ".join(missing)
        )
