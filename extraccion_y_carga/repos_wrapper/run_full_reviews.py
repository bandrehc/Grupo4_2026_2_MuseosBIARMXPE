"""run_full_reviews.py — Corrida masiva y reanudable de extracción de reseñas (Etapa 4).

Toma data/lugares/lugares_identificados.csv (aprobado en la Etapa 3) y extrae hasta
--max-reviews reseñas por lugar (techo, no meta — la gran mayoria de lugares tienen
muchisimas menos) usando googlemaps-reviews-scraper-es (Selenium).

Diseño
------
- Estado: logs/estado_scraping.db (SQLite), tabla `lugares`:
    lugar_id (PK, = id de Google), url_place, nombre, categoria_normalizada,
    distrito, provincia, departamento, n_reviews_google (reportado por Google en
    la Etapa 2), status (pendiente/en_progreso/completado/fallido), attempts,
    last_error, n_reviews_obtenidas, started_at, completed_at
- Resultados: se van agregando de forma incremental (append) a
    data/resenas/_raw_incremental.csv
  a medida que cada lugar termina.
- Cada worker mantiene UN navegador Chrome persistente (GoogleMapsScraper) que
  reutiliza entre lugares en vez de abrir uno nuevo por lugar (mucho mas eficiente
  que --workers de scraper.py, que abre un Chrome nuevo por URL). El navegador se
  reinicia cada --restart-every lugares para evitar degradacion de memoria en
  corridas de varios dias.
- Reintentos con backoff exponencial ante excepciones reales (a diferencia de
  mapScraper, aqui sort_by()/get_reviews() SI propagan excepciones — Selenium
  TimeoutException, WebDriverException, etc).
- Limitacion conocida: no se incluye el campo "idioma original / traducido automaticamente" — no existe
  en el repo base y agregar un selector nuevo sobre el DOM ofuscado de Google Maps
  se considero demasiado fragil para una corrida de produccion de varios dias.

Uso
----
  # Primera corrida (crea el estado si no existe)
  python run_full_reviews.py --lugares-csv ../data/lugares/lugares_identificados.csv \
      --max-reviews 25000 --concurrent 2 --pause-min 3 --pause-max 8

  # Reanudar: mismo comando, retoma automaticamente los lugares pendientes

  # Consolidar resultados finales una vez que todo termino
  python run_full_reviews.py --consolidate-only --out ../data/resenas/resenas_consolidadas
"""
import argparse
import csv
import logging
import random
import sqlite3
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRAPER_DIR = PROJECT_ROOT / "repos" / "googlemaps-reviews-scraper-es"
sys.path.insert(0, str(SCRAPER_DIR))

DEFAULT_DB = PROJECT_ROOT / "logs" / "estado_scraping.db"
DEFAULT_RAW_OUT = PROJECT_ROOT / "data" / "resenas" / "_raw_incremental.csv"

REVIEW_FIELDS = [
    "lugar_id", "nombre_lugar", "categoria_normalizada", "distrito", "provincia",
    "departamento", "id_review", "caption", "relative_date", "review_date",
    "retrieval_date", "rating", "username", "n_review_user", "url_user", "url_source",
]

SORT_IND = {"most_relevant": 0, "newest": 1, "highest_rating": 2, "lowest_rating": 3}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PROJECT_ROOT / "logs" / f"run_full_reviews_{datetime.now():%Y%m%d_%H%M%S}.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("run_full_reviews")

db_lock = threading.Lock()
csv_lock = threading.Lock()


def init_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lugares (
            lugar_id TEXT PRIMARY KEY,
            url_place TEXT,
            nombre TEXT,
            categoria_normalizada TEXT,
            distrito TEXT,
            provincia TEXT,
            departamento TEXT,
            n_reviews_google INTEGER,
            status TEXT NOT NULL DEFAULT 'pendiente',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            n_reviews_obtenidas INTEGER,
            started_at TEXT,
            completed_at TEXT
        )
    """)
    conn.commit()
    return conn


def load_lugares_into_db(conn, lugares_csv: Path):
    df = pd.read_csv(lugares_csv)
    rows = [
        (
            r["id"], r["url_place"], r["title"], r["categoria_normalizada"],
            r["distrito_final"], r["provincia_final"], r["departamento_final"],
            int(r["reviews"]) if pd.notna(r["reviews"]) else None,
        )
        for _, r in df.iterrows()
    ]
    with db_lock:
        conn.executemany(
            "INSERT OR IGNORE INTO lugares "
            "(lugar_id, url_place, nombre, categoria_normalizada, distrito, provincia, departamento, n_reviews_google) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    logger.info(f"Estado inicializado/actualizado: {len(rows)} lugares en total.")


def get_pending(conn, max_retries: int):
    with db_lock:
        cur = conn.execute(
            "SELECT lugar_id, url_place, nombre, categoria_normalizada, distrito, provincia, departamento, attempts "
            "FROM lugares WHERE status IN ('pendiente', 'en_progreso') "
            "OR (status = 'fallido' AND attempts < ?) "
            "ORDER BY lugar_id",
            (max_retries,),
        )
        return cur.fetchall()


def mark_en_progreso(conn, lugar_id):
    with db_lock:
        conn.execute(
            "UPDATE lugares SET status='en_progreso', attempts=attempts+1, started_at=? WHERE lugar_id=?",
            (datetime.now(timezone.utc).isoformat(), lugar_id),
        )
        conn.commit()


def mark_completado(conn, lugar_id, n_obtenidas):
    with db_lock:
        conn.execute(
            "UPDATE lugares SET status='completado', n_reviews_obtenidas=?, completed_at=?, last_error=NULL WHERE lugar_id=?",
            (n_obtenidas, datetime.now(timezone.utc).isoformat(), lugar_id),
        )
        conn.commit()


def mark_fallido(conn, lugar_id, error):
    with db_lock:
        conn.execute(
            "UPDATE lugares SET status='fallido', last_error=?, completed_at=? WHERE lugar_id=?",
            (str(error)[:500], datetime.now(timezone.utc).isoformat(), lugar_id),
        )
        conn.commit()


def append_reviews(raw_out: Path, rows: list[dict]):
    if not rows:
        return
    with csv_lock:
        file_exists = raw_out.exists() and raw_out.stat().st_size > 0
        with open(raw_out, "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            for row in rows:
                writer.writerow(row)


def scrape_lugar(scraper, lugar, args):
    lugar_id, url_place, nombre, categoria, distrito, provincia, departamento, attempts = lugar

    error = scraper.sort_by(url_place, SORT_IND[args.sort_by])
    if error != 0:
        raise RuntimeError("sort_by_failed")

    n = 0
    results = []
    retrieval_date = datetime.now()
    while n < args.max_reviews:
        reviews = scraper.get_reviews(n)
        if not reviews:
            break
        for r in reviews:
            row = dict(r)
            row.update({
                "lugar_id": lugar_id, "nombre_lugar": nombre,
                "categoria_normalizada": categoria, "distrito": distrito,
                "provincia": provincia, "departamento": departamento,
                "url_source": url_place,
            })
            results.append(row)
        n += len(reviews)
    return results


def worker(name, queue, conn, raw_out, args, retry_tracker):
    from googlemaps import GoogleMapsScraper

    procesados_desde_reinicio = 0
    scraper = GoogleMapsScraper(debug=False, turbo=False)
    scraper.__enter__()

    try:
        while True:
            try:
                lugar = queue.get(timeout=5)
            except Exception:
                # cola vacia por ahora — si no hay reintentos programados en vuelo,
                # ya no va a llegar mas trabajo y el worker puede terminar.
                if retry_tracker.count() == 0:
                    return
                continue

            lugar_id = lugar[0]
            mark_en_progreso(conn, lugar_id)

            try:
                if procesados_desde_reinicio >= args.restart_every:
                    logger.info(f"[{name}] Reiniciando navegador tras {procesados_desde_reinicio} lugares.")
                    scraper.__exit__(None, None, None)
                    scraper = GoogleMapsScraper(debug=False, turbo=False)
                    scraper.__enter__()
                    procesados_desde_reinicio = 0

                results = scrape_lugar(scraper, lugar, args)
                append_reviews(raw_out, results)
                mark_completado(conn, lugar_id, len(results))
                logger.info(f"[{name}] '{lugar[2]}' ({lugar_id}) -> {len(results)} reseña(s)")
                procesados_desde_reinicio += 1

            except Exception as e:
                logger.error(f"[{name}] FALLO en '{lugar[2]}' ({lugar_id}): {e}")
                mark_fallido(conn, lugar_id, e)
                attempts_so_far = lugar[7] + 1
                if attempts_so_far < args.max_retries:
                    backoff = min(30 * (2 ** (attempts_so_far - 1)), 600)
                    logger.info(f"[{name}] Reintentando '{lugar[2]}' en {backoff:.0f}s (intento {attempts_so_far}/{args.max_retries}).")
                    updated_lugar = lugar[:7] + (attempts_so_far,)
                    retry_tracker.schedule(queue, updated_lugar, backoff)
                else:
                    logger.warning(f"[{name}] '{lugar[2]}' agoto los {args.max_retries} intentos, queda como fallido definitivo.")
                # navegador probablemente en mal estado tras la excepcion -> reiniciar
                try:
                    scraper.__exit__(None, None, None)
                except Exception:
                    pass
                scraper = GoogleMapsScraper(debug=False, turbo=False)
                scraper.__enter__()
                procesados_desde_reinicio = 0

            time.sleep(random.uniform(args.pause_min, args.pause_max))
    finally:
        try:
            scraper.__exit__(None, None, None)
        except Exception:
            pass


class RetryTracker:
    """Cuenta reintentos programados via threading.Timer que todavia no se
    re-encolaron, para que los workers sepan que no deben terminar aunque la
    cola este momentaneamente vacia — sin esto, un lugar que falla quedaria
    'fallido' hasta el proximo relanzamiento manual del script, en vez de
    reintentarse dentro de la misma corrida (corrida de varios dias sin
    supervision constante)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._n = 0

    def count(self):
        with self._lock:
            return self._n

    def schedule(self, queue, lugar, delay_seconds):
        with self._lock:
            self._n += 1

        def _requeue():
            queue.put(lugar)
            with self._lock:
                self._n -= 1

        threading.Timer(delay_seconds, _requeue).start()


def run(args):
    conn = init_db(Path(args.db))
    load_lugares_into_db(conn, Path(args.lugares_csv))

    pending = get_pending(conn, args.max_retries)
    total_pending = len(pending)
    logger.info(f"Lugares pendientes de procesar en esta corrida: {total_pending}")
    if total_pending == 0:
        logger.info("Nada pendiente. Corrida completa.")
        return

    import queue as queue_mod
    q = queue_mod.Queue()
    for row in pending:
        q.put(row)

    raw_out = Path(args.out_raw)
    raw_out.parent.mkdir(parents=True, exist_ok=True)

    retry_tracker = RetryTracker()
    threads = [
        threading.Thread(target=worker, args=(f"w{i}", q, conn, raw_out, args, retry_tracker), daemon=True)
        for i in range(args.concurrent)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with db_lock:
        cur = conn.execute("SELECT status, COUNT(*) FROM lugares GROUP BY status")
        logger.info("Resumen de estado final: " + ", ".join(f"{s}={c}" for s, c in cur.fetchall()))


def consolidate(args):
    raw_out = Path(args.out_raw)
    if not raw_out.exists():
        logger.error(f"No existe {raw_out}, nada que consolidar.")
        sys.exit(1)

    reviews_df = pd.read_csv(raw_out)
    reviews_df = reviews_df.drop_duplicates(subset=["lugar_id", "id_review"])

    conn = init_db(Path(args.db))
    lugares_df = pd.read_sql("SELECT * FROM lugares", conn)
    lugares_df["n_reviews_obtenidas_real"] = (
        reviews_df.groupby("lugar_id").size().reindex(lugares_df["lugar_id"]).fillna(0).values
    )
    lugares_df["techo_alcanzado"] = lugares_df["n_reviews_obtenidas_real"] >= args.max_reviews
    lugares_df["cobertura_incompleta_vs_google"] = (
        lugares_df["n_reviews_obtenidas_real"] < lugares_df["n_reviews_google"].fillna(0)
    )

    out_base = Path(args.out)
    out_base.parent.mkdir(parents=True, exist_ok=True)

    size_mb = raw_out.stat().st_size / (1024 * 1024)
    if size_mb < 400:
        reviews_df.to_csv(out_base.with_suffix(".csv"), index=False, encoding="utf-8")
        logger.info(f"CSV consolidado escrito ({size_mb:.0f} MB crudo).")
    else:
        logger.warning(f"Archivo crudo de {size_mb:.0f} MB — se omite el .csv consolidado (Etapa 4 lo advirtio explicitamente), solo se genera .parquet particionado por departamento.")

    reviews_df = reviews_df.merge(
        lugares_df[["lugar_id", "departamento"]], on="lugar_id", how="left"
    )
    reviews_df.to_parquet(out_base.with_suffix(".parquet"), index=False, partition_cols=["departamento"])
    lugares_df.to_csv(PROJECT_ROOT / "data" / "resenas" / "cobertura_por_lugar.csv", index=False, encoding="utf-8")

    logger.info(f"Consolidado: {len(reviews_df)} reseñas de {lugares_df['status'].eq('completado').sum()} lugares completados -> {out_base}.parquet")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lugares-csv", default=str(PROJECT_ROOT / "data" / "lugares" / "lugares_identificados.csv"))
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out-raw", default=str(DEFAULT_RAW_OUT))
    ap.add_argument("--out", default=str(PROJECT_ROOT / "data" / "resenas" / "resenas_consolidadas"))
    ap.add_argument("--max-reviews", type=int, default=25000, dest="max_reviews")
    ap.add_argument("--sort-by", default="newest", choices=list(SORT_IND.keys()))
    ap.add_argument("--concurrent", type=int, default=2)
    ap.add_argument("--pause-min", type=float, default=3.0)
    ap.add_argument("--pause-max", type=float, default=8.0)
    ap.add_argument("--max-retries", type=int, default=3)
    ap.add_argument("--restart-every", type=int, default=150, help="Reiniciar el navegador cada N lugares por worker")
    ap.add_argument("--consolidate-only", action="store_true")
    args = ap.parse_args()

    if args.consolidate_only:
        consolidate(args)
        return

    t0 = time.time()
    run(args)
    logger.info(f"Tiempo total de esta corrida: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
