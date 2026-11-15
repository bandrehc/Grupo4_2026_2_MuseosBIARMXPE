"""run_search_batch.py — Corre un lote de queries contra mapScraper y adjunta metadata.

Este script es el runner "simple" usado para el piloto de la Etapa 1 (sin
checkpoint/resume — eso se construye en la Etapa 2 para la corrida completa de
todo el Peru). Aca el lote es chico y se corre de una sola sentada.

Uso
----
  python run_search_batch.py --queries-csv ../data/lugares/pilot_queries.csv \
      --out ../data/lugares/pilot_resultados.csv --lang es --country pe --concurrent 3
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

MAPSCRAPER_DIR = Path(__file__).resolve().parent.parent / "repos" / "mapScraper"
MAPSCRAPER_PY = MAPSCRAPER_DIR / ".venv" / "Scripts" / "python.exe"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries-csv", required=True, help="CSV generado por build_queries.py")
    ap.add_argument("--out", required=True, help="CSV final con resultados + metadata de la query")
    ap.add_argument("--lang", default="es")
    ap.add_argument("--country", default="pe")
    ap.add_argument("--concurrent", type=int, default=3)
    ap.add_argument("--limit", type=int, default=20, help="Limite de resultados por query (0 = sin limite; ADVERTENCIA: sin limite, Google pagina cientos de resultados de relevancia decreciente por query generica, y una sola query puede tardar >30s)")
    args = ap.parse_args()

    queries_df = pd.read_csv(args.queries_csv)
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw_out = out_path.with_name(out_path.stem + "_raw.csv")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8", dir=out_path.parent
    ) as fh:
        for q in queries_df["query_text"]:
            fh.write(q + "\n")
        queries_file = fh.name

    print(f"Corriendo {len(queries_df)} queries via mapScraper (concurrent={args.concurrent})...")
    # main.py --mode scrape (placesCrawlerV2) no expone fast/standard/complete, por eso
    # args.mode no se pasa al comando.
    cmd = [
        str(MAPSCRAPER_PY), "main.py", "--mode", "scrape",
        "--queries-file", queries_file,
        "--lang", args.lang, "--country", args.country,
        "--concurrent", str(args.concurrent),
        "--output-file", str(raw_out),
        "--log-level", "INFO",
    ]
    if args.limit:
        cmd += ["--limit", str(args.limit)]

    result = subprocess.run(cmd, cwd=str(MAPSCRAPER_DIR))
    if result.returncode != 0:
        print("ADVERTENCIA: mapScraper devolvio codigo de error", result.returncode)

    if not raw_out.exists():
        print("No se genero archivo de resultados (posible 0 resultados en todo el lote).")
        sys.exit(1)

    raw_df = pd.read_csv(raw_out)
    merged = raw_df.merge(
        queries_df,
        left_on="source_query", right_on="query_text",
        how="left", suffixes=("", "_query"),
    )
    merged.to_csv(out_path, index=False, encoding="utf-8")
    print(f"Resultados: {len(raw_df)} lugares -> {out_path}")

    # queries sin ningun resultado (para revisar ruido / cobertura)
    queries_con_resultado = set(raw_df["source_query"].unique()) if "source_query" in raw_df.columns else set()
    sin_resultado = queries_df[~queries_df["query_text"].isin(queries_con_resultado)]
    sin_resultado_path = out_path.with_name(out_path.stem + "_sin_resultado.csv")
    sin_resultado.to_csv(sin_resultado_path, index=False, encoding="utf-8")
    print(f"Queries sin ningun resultado: {len(sin_resultado)} / {len(queries_df)} -> {sin_resultado_path}")


if __name__ == "__main__":
    main()
