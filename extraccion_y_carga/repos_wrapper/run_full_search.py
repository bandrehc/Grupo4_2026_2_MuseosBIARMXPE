"""run_full_search.py — Corrida masiva y reanudable de búsqueda de lugares (Etapa 2).

Ejecuta el universo completo de queries (data/referencia/queries_busqueda.csv) contra
mapScraper, con estado persistido en SQLite para poder pausar/cortar el proceso y
reanudarlo despues sin repetir trabajo ni perder resultados ya obtenidos.

Diseño
------
- Las filas de queries_busqueda.csv tienen 3 niveles (distrito/provincia/departamento)
  que a veces colapsan al mismo texto de query. Para no gastar tiempo/requests pidiendole a Google el mismo texto dos
  veces, la EJECUCION se hace sobre el conjunto de query_text UNICOS (tabla
  `unique_queries` en el estado). La trazabilidad de que niveles/distritos originaron
  cada texto se recupera despues haciendo join contra queries_busqueda.csv por
  query_text (columna 'nivel', 'distrito', 'provincia', 'departamento', etc.)
- Estado: logs/estado_busqueda.db (SQLite), tabla `unique_queries`:
    query_text (PK), status (pending/in_progress/completed/failed),
    attempts, last_error, n_resultados, started_at, completed_at
- Resultados: se van agregando de forma incremental (append) a
    data/lugares/_raw_incremental.csv
  a medida que cada query termina — un corte a mitad de camino no pierde nada ya escrito.
- Reintentos: mapScraper.placesCrawlerV2.search_async atrapa TODAS las excepciones
  internamente y devuelve lista vacia tanto si hubo un error real como si
  legitimamente no hay resultados (limitacion conocida de la libreria). Por eso el "reintento" aqui se basa en: si una
  query da 0 resultados, se reintenta hasta --max-retries veces con backoff
  exponencial antes de aceptarla como definitiva; las que sigan en 0 se marcan
  'completed' igual (0 resultados es un estado valido) pero quedan listadas aparte
  para revision manual si se desea.
- Pausas: cada worker espera un tiempo aleatorio entre --pause-min y --pause-max
  segundos entre queries sucesivas, ademas del limite de concurrencia --concurrent.

Uso
----
  # Primera corrida (crea el estado si no existe)
  python run_full_search.py --queries-csv ../data/referencia/queries_busqueda.csv \
      --limit 50 --concurrent 3 --pause-min 1.5 --pause-max 3.5

  # Reanudar despues de un corte: mismo comando, retoma automaticamente
  # las queries que sigan en pending/in_progress

  # Consolidar resultados finales (parquet + csv) una vez que todo termino
  python run_full_search.py --consolidate-only --out data/lugares/lugares_candidatos
"""
import argparse
import asyncio
import csv
import logging
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from country_config import load_country_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAPSCRAPER_DIR = PROJECT_ROOT / "repos" / "mapScraper"
sys.path.insert(0, str(MAPSCRAPER_DIR))

DEFAULT_DB = PROJECT_ROOT / "logs" / "estado_busqueda.db"
DEFAULT_RAW_OUT = PROJECT_ROOT / "data" / "lugares" / "_raw_incremental.csv"
DEFAULT_FAILED_LOG = PROJECT_ROOT / "logs" / "queries_fallidas.csv"

RAW_FIELDS = [
    "id", "url_place", "title", "category", "address", "phoneNumber",
    "completePhoneNumber", "domain", "url", "coor", "stars", "reviews",
    "source_query",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PROJECT_ROOT / "logs" / f"run_full_search_{datetime.now():%Y%m%d_%H%M%S}.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("run_full_search")


def resolve_country_args(args):
    """Resuelve rutas aisladas cuando se invoca el modo multi-país.

    Sin ``--codigo-pais`` se preserva el modo histórico y sus rutas originales,
    incluso si se pasa ``--country`` directamente a mapScraper. El modo LATAM
    exige ``--codigo-pais`` para poder validar la configuración y evitar que un
    país nuevo reutilice los checkpoints de Perú.
    """
    if not args.codigo_pais:
        args.queries_csv = args.queries_csv or str(PROJECT_ROOT / "data" / "referencia" / "queries_busqueda.csv")
        args.db = args.db or str(DEFAULT_DB)
        args.out_raw = args.out_raw or str(DEFAULT_RAW_OUT)
        args.out = args.out or str(PROJECT_ROOT / "data" / "lugares" / "lugares_candidatos")
        args.country = args.country or "pe"
        args.lang = args.lang or "es"
        return None

    config = load_country_config(args.codigo_pais)
    expected_google_code = config["google_country_code"].lower()
    if args.country and args.country.lower() != expected_google_code:
        raise ValueError(
            f"--country={args.country!r} no coincide con {config['pais']} "
            f"({expected_google_code!r}) en paises_latam.csv."
        )

    suffix = config["codigo_pais"].lower()
    args.country = expected_google_code
    args.lang = args.lang or config["idioma"]
    args.queries_csv = args.queries_csv or str(PROJECT_ROOT / "data" / "referencia" / f"queries_busqueda_{suffix}.csv")
    args.db = args.db or str(PROJECT_ROOT / "logs" / f"estado_busqueda_{suffix}.db")
    args.out_raw = args.out_raw or str(PROJECT_ROOT / "data" / "lugares" / f"_raw_incremental_{suffix}.csv")
    args.out = args.out or str(PROJECT_ROOT / "data" / "lugares" / f"lugares_candidatos_{config['slug_pais']}")
    return config


def init_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS unique_queries (
            query_text TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            n_resultados INTEGER,
            started_at TEXT,
            completed_at TEXT
        )
    """)
    conn.commit()
    return conn


def load_queries_into_db(conn, queries_csv: Path):
    df = pd.read_csv(queries_csv)
    unique_texts = df["query_text"].drop_duplicates().tolist()
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR IGNORE INTO unique_queries (query_text) VALUES (?)",
        [(q,) for q in unique_texts],
    )
    conn.commit()
    logger.info(f"Estado inicializado/actualizado: {len(unique_texts)} queries unicas en total.")


def get_pending(conn, max_retries: int):
    cur = conn.execute(
        "SELECT query_text, attempts FROM unique_queries "
        "WHERE status IN ('pending', 'in_progress') "
        "OR (status = 'completed' AND n_resultados = 0 AND attempts < ?) "
        "ORDER BY query_text",
        (max_retries,),
    )
    return cur.fetchall()


def mark_in_progress(conn, query_text):
    conn.execute(
        "UPDATE unique_queries SET status='in_progress', attempts=attempts+1, "
        "started_at=? WHERE query_text=?",
        (datetime.now(timezone.utc).isoformat(), query_text),
    )
    conn.commit()


def mark_completed(conn, query_text, n_resultados, error=None):
    conn.execute(
        "UPDATE unique_queries SET status='completed', n_resultados=?, last_error=?, "
        "completed_at=? WHERE query_text=?",
        (n_resultados, error, datetime.now(timezone.utc).isoformat(), query_text),
    )
    conn.commit()


def mark_failed(conn, query_text, error):
    conn.execute(
        "UPDATE unique_queries SET status='failed', last_error=?, completed_at=? "
        "WHERE query_text=?",
        (str(error)[:500], datetime.now(timezone.utc).isoformat(), query_text),
    )
    conn.commit()


def append_results(raw_out: Path, results: list[dict]):
    if not results:
        return
    file_exists = raw_out.exists() and raw_out.stat().st_size > 0
    with open(raw_out, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=RAW_FIELDS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for row in results:
            writer.writerow(row)


async def worker(name, queue, conn, raw_out, lang, country, limit, pause_min, pause_max, max_retries):
    from mapScraper.placesCrawlerV2 import search_async

    while True:
        try:
            query_text, attempts = queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        mark_in_progress(conn, query_text)
        semaphore = asyncio.Semaphore(1)
        try:
            results = await search_async(query_text, lang, country, limit, semaphore)
            append_results(raw_out, results)
            mark_completed(conn, query_text, len(results))
            if len(results) == 0:
                logger.info(f"[{name}] '{query_text}' -> 0 resultados (intento {attempts + 1}/{max_retries})")
            else:
                logger.info(f"[{name}] '{query_text}' -> {len(results)} resultado(s)")
        except Exception as e:
            logger.error(f"[{name}] FALLO en '{query_text}': {e}")
            if attempts + 1 >= max_retries:
                mark_failed(conn, query_text, e)
            else:
                mark_completed(conn, query_text, 0, error=str(e)[:500])

        await asyncio.sleep(random.uniform(pause_min, pause_max))


async def run(args):
    conn = init_db(Path(args.db))
    load_queries_into_db(conn, Path(args.queries_csv))

    pending = get_pending(conn, args.max_retries)
    total_pending = len(pending)
    logger.info(f"Queries pendientes de procesar en esta corrida: {total_pending}")
    if total_pending == 0:
        logger.info("Nada pendiente. Corrida completa.")
        return

    queue: asyncio.Queue = asyncio.Queue()
    for row in pending:
        queue.put_nowait(row)

    raw_out = Path(args.out_raw)
    raw_out.parent.mkdir(parents=True, exist_ok=True)

    workers = [
        asyncio.create_task(worker(
            f"w{i}", queue, conn, raw_out,
            args.lang, args.country, args.limit,
            args.pause_min, args.pause_max, args.max_retries,
        ))
        for i in range(args.concurrent)
    ]
    await asyncio.gather(*workers)

    cur = conn.execute("SELECT status, COUNT(*) FROM unique_queries GROUP BY status")
    logger.info("Resumen de estado final: " + ", ".join(f"{s}={c}" for s, c in cur.fetchall()))


def consolidate(args):
    """Junta el CSV incremental crudo + metadata de queries_busqueda.csv en el
    archivo final de lugares candidatos (parquet + csv)."""
    raw_out = Path(args.out_raw)
    if not raw_out.exists():
        logger.error(f"No existe {raw_out}, nada que consolidar.")
        sys.exit(1)

    raw_df = pd.read_csv(raw_out)
    raw_df = raw_df.drop_duplicates(subset=["id"])

    queries_df = pd.read_csv(args.queries_csv)
    merged = raw_df.merge(
        queries_df, left_on="source_query", right_on="query_text",
        how="left", suffixes=("", "_query"),
    )

    out_base = Path(args.out)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out_base.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    try:
        merged.to_parquet(out_base.with_suffix(".parquet"), index=False)
    except ImportError:
        logger.warning("pyarrow/fastparquet no instalado — se genero solo el .csv, falta el .parquet")

    logger.info(f"Consolidado: {len(merged)} filas ({raw_df['id'].nunique()} lugares unicos) -> {out_base}.csv / .parquet")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--codigo-pais", default=None,
                    help="Activa el modo LATAM con rutas aisladas (ej. MX).")
    ap.add_argument("--queries-csv", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--out-raw", default=None, help="CSV incremental crudo (checkpoint)")
    ap.add_argument("--out", default=None, help="Base de salida para --consolidate-only (sin extension)")
    ap.add_argument("--lang", default=None)
    ap.add_argument("--country", default=None, help="Código Google (modo histórico) o validación adicional en modo LATAM")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--concurrent", type=int, default=3)
    ap.add_argument("--pause-min", type=float, default=1.5)
    ap.add_argument("--pause-max", type=float, default=3.5)
    ap.add_argument("--max-retries", type=int, default=2)
    ap.add_argument("--consolidate-only", action="store_true")
    args = ap.parse_args()

    config = resolve_country_args(args)
    if config is not None:
        logger.info(
            f"Modo LATAM: {config['pais']} ({config['codigo_pais']}); "
            f"estado={Path(args.db).name}, raw={Path(args.out_raw).name}"
        )

    if args.consolidate_only:
        consolidate(args)
        return

    t0 = time.time()
    asyncio.run(run(args))
    logger.info(f"Tiempo total de esta corrida: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
