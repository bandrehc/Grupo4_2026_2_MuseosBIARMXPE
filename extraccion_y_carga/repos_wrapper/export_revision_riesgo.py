"""export_revision_riesgo.py — Exporta el subconjunto de lugares de mayor riesgo
(confianza baja + distrito real no coincide con el de la query) para revisión manual.

Genera dos JSON (data/lugares/_revision_riesgo.json y _revision_riesgo_resumen.json)
listos para inyectar en una vista HTML interactiva (ver la que se publicó como
artifact durante la revisión de la Etapa 3 — este script solo regenera los datos,
no el HTML).

Uso
----
  python export_revision_riesgo.py
"""
import json
import unicodedata
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _norm(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()


def main():
    df = pd.read_csv(PROJECT_ROOT / "data" / "lugares" / "lugares_identificados.csv")
    riesgo = df[(df["confianza_clasificacion"] == "baja") & (~df["coincide_con_distrito_de_consulta"])].copy()

    riesgo["depto_query_norm"] = riesgo["departamento"].map(_norm)
    riesgo["depto_real_norm"] = riesgo["departamento_final"].map(_norm)
    riesgo["severidad"] = riesgo.apply(
        lambda r: "grave" if r["depto_query_norm"] != r["depto_real_norm"] else "revisar", axis=1
    )

    cols = [
        "id", "title", "category", "categoria_normalizada", "palabra_clave",
        "distrito", "provincia", "departamento",
        "distrito_final", "provincia_final", "departamento_final",
        "url_place", "stars", "reviews", "severidad",
    ]
    out = riesgo[cols].copy()
    out["category"] = out["category"].fillna("(sin categoria de Google)")
    out["stars"] = out["stars"].fillna(0)
    out["reviews"] = out["reviews"].fillna(0).astype(int)

    out_dir = PROJECT_ROOT / "data" / "lugares"
    out.to_json(out_dir / "_revision_riesgo.json", orient="records", force_ascii=False)

    resumen = {
        "top_keywords": riesgo["palabra_clave"].value_counts().head(8).to_dict(),
        "top_google_cat": riesgo["category"].value_counts().head(8).to_dict(),
        "por_categoria_normalizada": riesgo["categoria_normalizada"].value_counts().to_dict(),
        "total": len(riesgo),
        "graves": int((riesgo["severidad"] == "grave").sum()),
    }
    with open(out_dir / "_revision_riesgo_resumen.json", "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False)

    print(f"{len(out)} lugares exportados -> {out_dir / '_revision_riesgo.json'}")
    print(f"Severidad: {riesgo['severidad'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
