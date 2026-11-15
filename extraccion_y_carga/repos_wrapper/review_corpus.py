"""Lectura del corpus sin depender del navegador ni iniciar una extracción."""
from pathlib import Path

import pandas as pd

REVIEW_FIELDS = [
    "google_place_id", "nombre_lugar", "categoria_google", "distrito", "provincia",
    "departamento", "id_review", "caption", "relative_date", "review_date",
    "retrieval_date", "rating", "username", "n_review_user", "url_user", "url_source",
]


def load_consolidation_reviews(raw_out, final_csv):
    """Conserva el corpus final aunque se haya eliminado el crudo por espacio.

    Una corrida posterior puede producir solo un incremental nuevo. Siempre se
    une con el final anterior, sin modificar ninguno de los insumos al leerlos.
    """
    paths = []
    for path in (Path(final_csv), Path(raw_out)):
        if path.is_file() and path.resolve() not in [p.resolve() for p in paths]:
            paths.append(path)
    if not paths:
        raise FileNotFoundError(f"No existe ni {raw_out} ni {final_csv}.")
    frames = []
    for path in paths:
        frame = pd.read_csv(path, dtype={"google_place_id": str, "id_review": str})
        if list(frame.columns) != REVIEW_FIELDS:
            raise ValueError(f"{path}: las columnas no cumplen el contrato de reseñas.")
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)
