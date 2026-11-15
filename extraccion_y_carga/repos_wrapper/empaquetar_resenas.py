"""empaquetar_resenas.py — Comprime un CSV de reseñas en partes .csv.gz aptas para GitHub (<100 MB).

GitHub rechaza archivos de mas de 100 MB. Los CSV de reseñas (crudos y consolidado) los superan,
pero comprimidos con gzip caen a ~25 % y se leen directo con pandas.

Uso:
    python repos_wrapper/empaquetar_resenas.py data/resenas/comentarios_museos_crudo_argentina.csv
    python repos_wrapper/empaquetar_resenas.py data/resenas/comentarios_museos_crudo_mexico.csv --max-mb 80

Salida (junto al CSV, en data/resenas/paquetes/):
    <nombre>.csv.gz                  si cabe en una sola parte
    <nombre>.part01.csv.gz, ...      si hay que partirlo (cada parte con su cabecera)

Lectura:
    pd.read_csv("data/resenas/paquetes/<nombre>.csv.gz")
    pd.concat(pd.read_csv(p) for p in sorted(Path("data/resenas/paquetes").glob("<nombre>.part*.csv.gz")))

Verifica al final que filas y id_review unicos coincidan con el original. No modifica ni borra el CSV.
"""
import argparse
import gzip
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "data" / "resenas" / "paquetes"
CHUNK = 100_000


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--max-mb", type=float, default=90.0, help="tamaño maximo por parte comprimida (default 90)")
    args = ap.parse_args()

    src = Path(args.csv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tope = int(args.max_mb * 1024 * 1024)
    stem = src.name[: -len(".csv")]

    for viejo in list(OUT_DIR.glob(f"{stem}.csv.gz")) + list(OUT_DIR.glob(f"{stem}.part*.csv.gz")):
        viejo.unlink()   # solo paquetes generados por este script, nunca el CSV de origen

    partes, n_filas, ids = [], 0, set()
    parte = None
    fh = None

    def abrir():
        nonlocal fh, parte
        if fh:
            fh.close()
        parte = OUT_DIR / f"{stem}.part{len(partes) + 1:02d}.csv.gz"
        partes.append(parte)
        fh = gzip.open(parte, "wt", encoding="utf-8", newline="")
        return True

    abrir()
    nueva = True
    for df in pd.read_csv(src, chunksize=CHUNK, low_memory=False):
        n_filas += len(df)
        if "id_review" in df:
            ids.update(df["id_review"].astype(str))
        fh.write(df.to_csv(index=False, header=nueva))
        nueva = False
        fh.flush()
        if parte.stat().st_size > tope:
            abrir()
            nueva = True
    fh.close()
    partes = [p for p in partes if p.exists() and p.stat().st_size > 30]   # descarta parte vacia final

    if len(partes) == 1:
        final = OUT_DIR / f"{stem}.csv.gz"
        partes[0].rename(final)
        partes = [final]

    # verificacion de integridad
    n_chk, ids_chk = 0, set()
    for p in partes:
        for df in pd.read_csv(p, chunksize=CHUNK, low_memory=False):
            n_chk += len(df)
            if "id_review" in df:
                ids_chk.update(df["id_review"].astype(str))
    ok = (n_chk == n_filas) and (ids_chk == ids)
    print(f"{src.name}: {n_filas:,} filas, {len(ids):,} id_review unicos -> {len(partes)} parte(s)")
    for p in partes:
        print(f"  {p.relative_to(PROJECT_ROOT)}  {p.stat().st_size / 1e6:.1f} MB")
    print("VERIFICACION:", "OK, identico al original" if ok else "FALLO: no coincide")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
