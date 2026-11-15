"""scrape_comentarios_museos.py — Extracción de reseñas de museos por país.

Toma un ``base_museos_<pais>.csv`` filtrado por ``category == "Museo"`` exacto y
extrae hasta --max-reviews reseñas por lugar usando
googlemaps-reviews-scraper-es (Selenium). Sin ``--country`` conserva los paths
históricos de Perú; con un país configurado usa outputs y SQLite aislados.

- Universo: solo museos (base_museos_peru.csv), no el dataset completo.
- Salida propia: data/resenas/comentarios_museos_crudo.csv (no mezcla con
  _raw_incremental.csv de la corrida general).
- Estado propio: logs/estado_scraping_museos.db (no comparte estado con la corrida
  general, que tiene su propio tope de 25000/lugar y su propia cola).
- Tope por defecto: 30000 reseñas por lugar (si el lugar tiene menos, el loop
  corta solo apenas get_reviews() deja de devolver resultados nuevos y pasa al
  siguiente lugar).
- Concurrencia fija en 3 workers, cada uno con su propio Chrome persistente.
- Sin delays variables/aleatorios entre lugares (a diferencia de run_full_reviews.py,
  que usa random.uniform(pause_min, pause_max)): la pausa entre lugares es un valor
  fijo (--pause, default 0s). El reintento tras un fallo real usa un backoff fijo
  (no exponencial ni aleatorio) para no introducir variabilidad.
- Progreso en terminal vía tqdm, a nivel de establecimiento (1 tick = 1 museo
  terminado, ok o fallido), con postfix de reseñas acumuladas.

El campo `google_place_id` en la salida es el mismo valor que la columna `id` de
base_museos_peru.csv — permite hacer join entre ambos archivos.

Uso
----
  python scrape_comentarios_museos.py

  # País habilitado en data/referencia/paises_latam.csv
  python scrape_comentarios_museos.py --country MX

  # Reanudar (retoma automáticamente los museos pendientes/fallidos con reintentos disponibles):
  python scrape_comentarios_museos.py

  # Consolidar al terminar (no scrapea; deduplica y escribe los entregables finales):
  python scrape_comentarios_museos.py --consolidate-only
"""
import argparse
import csv
import logging
import queue as queue_mod
import shutil
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm

from country_config import load_country_config
from review_corpus import REVIEW_FIELDS, load_consolidation_reviews

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRAPER_DIR = PROJECT_ROOT / "repos" / "googlemaps-reviews-scraper-es"
sys.path.insert(0, str(SCRAPER_DIR))

DEFAULT_MUSEOS_CSV = PROJECT_ROOT / "data" / "lugares" / "base_museos_peru.csv"
DEFAULT_DB = PROJECT_ROOT / "logs" / "estado_scraping_museos.db"
DEFAULT_RAW_OUT = PROJECT_ROOT / "data" / "resenas" / "comentarios_museos_crudo.csv"
DEFAULT_CONSOLIDADO = PROJECT_ROOT / "data" / "resenas" / "resenas_museos_consolidadas"

SORT_IND = {"most_relevant": 0, "newest": 1, "highest_rating": 2, "lowest_rating": 3}

RETRY_DELAY_SECONDS = 15  # fijo, no exponencial ni aleatorio

# Modo opcional para museos de muy alto volumen. Extrae y poda solo los
# bloques nuevos del DOM en vez de serializar/reprocesar toda la página en cada
# scroll. Se deriva de scrape_qorikancha.py, pero queda integrado al flujo con
# SQLite, workers, consolidación y QA del país.
JS_ALTO_VOLUMEN_EXPANDIR = """
const bloques = document.querySelectorAll('div.jftiEf');
for (let i = arguments[0]; i < bloques.length; i++) {
  const boton = bloques[i].querySelector('button.w8nwRe.kyuRq');
  if (boton) boton.click();
}
return bloques.length;
"""
JS_ALTO_VOLUMEN_EXTRAER = """
const bloques = document.querySelectorAll('div.jftiEf');
const salida = [];
for (let i = arguments[0]; i < bloques.length; i++) salida.push(bloques[i].outerHTML);
return salida;
"""
JS_ALTO_VOLUMEN_PODAR = """
const bloques = document.querySelectorAll('div.jftiEf');
let eliminados = 0;
for (let i = 0; i < arguments[0] && i < bloques.length; i++) {
  if (bloques[i].parentNode) { bloques[i].remove(); eliminados++; }
}
return eliminados;
"""
JS_ALTO_VOLUMEN_SCROLL = """
const panel = document.querySelector('div.m6QErb.DxyBCb.kA9KIf.dS8AEf');
if (panel) { panel.scrollTop = panel.scrollHeight; return panel.scrollHeight; }
return -1;
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.FileHandler(PROJECT_ROOT / "logs" / f"scrape_museos_{datetime.now():%Y%m%d_%H%M%S}.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("scrape_comentarios_museos")

db_lock = threading.Lock()
csv_lock = threading.Lock()
pbar_lock = threading.Lock()


REQUIRED_MUSEUM_COLUMNS = {
    "id", "url_place", "title", "category", "reviews",
    "distrito_final", "provincia_final", "departamento_final",
}


def resolve_country_args(args):
    """Resuelve rutas por país sin cambiar las rutas históricas por defecto."""
    if not args.codigo_pais:
        args.museos_csv = args.museos_csv or str(DEFAULT_MUSEOS_CSV)
        args.db = args.db or str(DEFAULT_DB)
        args.out_raw = args.out_raw or str(DEFAULT_RAW_OUT)
        args.out = args.out or str(DEFAULT_CONSOLIDADO)
        args.out_cobertura = args.out_cobertura or str(
            PROJECT_ROOT / "data" / "resenas" / "cobertura_museos_por_lugar.csv"
        )
        return None

    country = load_country_config(args.codigo_pais)
    suffix = country["slug_pais"]
    code = country["codigo_pais"].lower()
    args.museos_csv = args.museos_csv or str(PROJECT_ROOT / "data" / "lugares" / f"base_museos_{suffix}.csv")
    args.db = args.db or str(PROJECT_ROOT / "logs" / f"estado_scraping_museos_{code}.db")
    args.out_raw = args.out_raw or str(PROJECT_ROOT / "data" / "resenas" / f"comentarios_museos_crudo_{suffix}.csv")
    args.out = args.out or str(PROJECT_ROOT / "data" / "resenas" / f"resenas_museos_consolidadas_{suffix}")
    args.out_cobertura = args.out_cobertura or str(
        PROJECT_ROOT / "data" / "resenas" / f"cobertura_museos_por_lugar_{suffix}.csv"
    )
    return country


def init_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS museos (
            lugar_id TEXT PRIMARY KEY,
            url_place TEXT,
            nombre TEXT,
            categoria_google TEXT,
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


def load_museos_into_db(
    conn,
    museos_csv: Path,
    limit_museos: int | None = None,
    max_google_reviews: int | None = None,
):
    df = pd.read_csv(museos_csv)
    missing = REQUIRED_MUSEUM_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"{museos_csv.name} no es compatible con el scraper; faltan columnas: "
            + ", ".join(sorted(missing))
        )
    if max_google_reviews is not None:
        if max_google_reviews <= 0:
            raise ValueError("--max-google-reviews debe ser mayor que cero.")
        df = df[pd.to_numeric(df["reviews"], errors="coerce").fillna(0).le(max_google_reviews)].copy()
    if limit_museos is not None:
        if limit_museos <= 0:
            raise ValueError("--limit-museos debe ser mayor que cero.")
        # Orden estable para que el mismo piloto sea reproducible al reanudarlo.
        df = df.sort_values("id").head(limit_museos).copy()
    if df.empty:
        raise ValueError("El filtro de piloto no dejó museos para procesar.")
    rows = [
        (
            r["id"], r["url_place"], r["title"], r["category"],
            r["distrito_final"], r["provincia_final"], r["departamento_final"],
            int(r["reviews"]) if pd.notna(r["reviews"]) else None,
        )
        for _, r in df.iterrows()
    ]
    with db_lock:
        conn.executemany(
            "INSERT OR IGNORE INTO museos "
            "(lugar_id, url_place, nombre, categoria_google, distrito, provincia, departamento, n_reviews_google) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    logger.info(f"Estado inicializado/actualizado: {len(rows)} museos en total.")
    return len(rows)


def get_pending(conn, max_retries: int):
    with db_lock:
        cur = conn.execute(
            "SELECT lugar_id, url_place, nombre, categoria_google, distrito, provincia, departamento, attempts "
            "FROM museos WHERE status IN ('pendiente', 'en_progreso') "
            "OR (status = 'fallido' AND attempts < ?) "
            "ORDER BY lugar_id",
            (max_retries,),
        )
        return cur.fetchall()


def mark_en_progreso(conn, lugar_id):
    with db_lock:
        conn.execute(
            "UPDATE museos SET status='en_progreso', attempts=attempts+1, started_at=? WHERE lugar_id=?",
            (datetime.now(timezone.utc).isoformat(), lugar_id),
        )
        conn.commit()


def mark_completado(conn, lugar_id, n_obtenidas):
    with db_lock:
        conn.execute(
            "UPDATE museos SET status='completado', n_reviews_obtenidas=?, completed_at=?, last_error=NULL WHERE lugar_id=?",
            (n_obtenidas, datetime.now(timezone.utc).isoformat(), lugar_id),
        )
        conn.commit()


def mark_fallido(conn, lugar_id, error):
    with db_lock:
        conn.execute(
            "UPDATE museos SET status='fallido', last_error=?, completed_at=? WHERE lugar_id=?",
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


def _enriquecer_review(review, lugar):
    lugar_id, url_place, nombre, categoria, distrito, provincia, departamento, _ = lugar
    row = dict(review)
    row.update({
        "google_place_id": lugar_id, "nombre_lugar": nombre,
        "categoria_google": categoria, "distrito": distrito,
        "provincia": provincia, "departamento": departamento,
        "url_source": url_place,
    })
    return row


def scrape_lugar_normal(scraper, lugar, args, raw_out):
    lugar_id, url_place, nombre, categoria, distrito, provincia, departamento, attempts = lugar

    error = scraper.sort_by(url_place, SORT_IND[args.sort_by])
    if error != 0:
        raise RuntimeError("sort_by_failed")

    n = 0
    # max_reviews=0 significa no aplicar una cuota artificial. El extractor
    # sigue hasta que Google deja de entregar bloques nuevos para este lugar.
    # Los workers se paralelizan entre museos, no dentro del mismo museo: abrir
    # varios workers sobre un mismo URL empezaría desde el principio y duplicaría
    # scroll/transferencia antes de la deduplicación final.
    while args.max_reviews == 0 or n < args.max_reviews:
        reviews = scraper.get_reviews(n)
        if not reviews:
            # sort_by() ya confirmó que Google mostró tarjetas de reseñas. Si el primer
            # lote no se puede parsear o guardar, no es válido registrar el lugar como
            # extracción exitosa con cero reseñas.
            if n == 0:
                raise RuntimeError("review_cards_not_persisted")
            break
        # Cada tanda se persiste de inmediato. Si Chrome falla a mitad de un
        # museo, una futura pasada puede repetir scroll, pero la consolidación
        # deduplica por Place ID + review ID y no se pierde lo ya obtenido.
        append_reviews(raw_out, [_enriquecer_review(review, lugar) for review in reviews])
        n += len(reviews)
    return n


def scrape_lugar_alto_volumen(scraper, lugar, args, raw_out):
    """Extracción incremental y podada para un museo de volumen muy alto."""
    _, url_place, _, _, _, _, _, _ = lugar
    error = scraper.sort_by(url_place, SORT_IND[args.sort_by])
    if error != 0:
        raise RuntimeError("sort_by_failed")

    parse_review = scraper._GoogleMapsScraper__parse
    total = 0
    procesados_en_dom = 0
    sin_progreso = 0
    vistos: set[str] = set()
    inicio = time.time()
    while args.max_reviews == 0 or total < args.max_reviews:
        if args.high_volume_time_budget > 0 and time.time() - inicio > args.high_volume_time_budget:
            logger.warning("Presupuesto de alto volumen agotado para %s; se conserva lo ya escrito.", lugar[2])
            break
        tanda_inicio = time.time()
        scraper.driver.execute_script(JS_ALTO_VOLUMEN_SCROLL)
        time.sleep(1.2)
        scraper.driver.execute_script(JS_ALTO_VOLUMEN_EXPANDIR, procesados_en_dom)
        time.sleep(0.4)
        htmls = scraper.driver.execute_script(JS_ALTO_VOLUMEN_EXTRAER, procesados_en_dom)
        if time.time() - tanda_inicio > args.high_volume_batch_timeout:
            raise RuntimeError("alto_volumen_tanda_lenta")
        if not htmls:
            sin_progreso += 1
            if sin_progreso >= args.high_volume_sin_progreso:
                break
            continue

        rows = []
        for html in htmls:
            block = BeautifulSoup(html, "html.parser").find("div", class_="jftiEf")
            if block is None:
                continue
            review = parse_review(block)
            review_id = review.get("id_review")
            if not review_id or review_id in vistos:
                continue
            vistos.add(review_id)
            rows.append(_enriquecer_review(review, lugar))
        procesados_en_dom += len(htmls)
        if rows:
            append_reviews(raw_out, rows)
            total += len(rows)
            sin_progreso = 0
        else:
            sin_progreso += 1
            if sin_progreso >= args.high_volume_sin_progreso:
                break
        # Conserva aproximadamente 200 tarjetas recientes; evita que el DOM
        # crezca sin límite y degrada cada scroll a costo cuadrático.
        if procesados_en_dom > 400:
            podados = scraper.driver.execute_script(JS_ALTO_VOLUMEN_PODAR, procesados_en_dom - 200)
            procesados_en_dom -= int(podados or 0)
    # Igual que en el modo normal: un panel de reseñas activo que no deja ningún registro
    # guardado es un fallo de calidad. Queda reintentable en SQLite en lugar de inflar la
    # completitud con un falso cero.
    if total == 0:
        raise RuntimeError("review_cards_not_persisted")
    return total


def scrape_lugar(scraper, lugar, args, raw_out):
    if args.optimized_high_volume:
        return scrape_lugar_alto_volumen(scraper, lugar, args, raw_out)
    return scrape_lugar_normal(scraper, lugar, args, raw_out)


def nuevo_scraper(name, optimized_high_volume=False, intentos=5):
    """Arranca un Chrome nuevo, reintentando con backoff.

    Si Chrome no arranca (RAM ocupada por navegadores huerfanos, chromedriver
    trabado, etc.) esto lanzaba una excepcion que se escapaba del `except` del
    worker, mataba al worker en silencio y dejaba museos sin procesar.
    """
    from googlemaps import GoogleMapsScraper
    ultimo_error = None
    for intento in range(1, intentos + 1):
        try:
            sc = GoogleMapsScraper(debug=False, turbo=optimized_high_volume)
            sc.__enter__()
            return sc
        except Exception as e:
            ultimo_error = e
            espera = min(10 * intento, 60)
            logger.error(f"[{name}] No arranco Chrome (intento {intento}/{intentos}): {e}. Reintento en {espera}s.")
            time.sleep(espera)
    raise RuntimeError(f"[{name}] Chrome no arranco tras {intentos} intentos: {ultimo_error}")


def worker(name, q, conn, raw_out, args, retry_tracker, pbar, stats):
    procesados_desde_reinicio = 0
    scraper = nuevo_scraper(name, args.optimized_high_volume)

    try:
        while True:
            try:
                lugar = q.get(timeout=5)
            except Exception:
                if retry_tracker.count() == 0:
                    return
                continue

            lugar_id = lugar[0]
            mark_en_progreso(conn, lugar_id)

            try:
                if procesados_desde_reinicio >= args.restart_every:
                    logger.info(f"[{name}] Reiniciando navegador tras {procesados_desde_reinicio} museos.")
                    scraper.__exit__(None, None, None)
                    scraper = nuevo_scraper(name, args.optimized_high_volume)
                    procesados_desde_reinicio = 0

                n_reviews = scrape_lugar(scraper, lugar, args, raw_out)
                mark_completado(conn, lugar_id, n_reviews)
                logger.info(f"[{name}] '{lugar[2]}' ({lugar_id}) -> {n_reviews} reseña(s)")
                procesados_desde_reinicio += 1

                with pbar_lock:
                    stats["completados"] += 1
                    stats["reviews"] += n_reviews
                    pbar.set_postfix(ok=stats["completados"], fallidos=stats["fallidos"], reviews=stats["reviews"])
                    pbar.update(1)

            except Exception as e:
                logger.error(f"[{name}] FALLO en '{lugar[2]}' ({lugar_id}): {e}")
                mark_fallido(conn, lugar_id, e)
                attempts_so_far = lugar[7] + 1
                if attempts_so_far < args.max_retries:
                    tqdm.write(f"[{name}] Reintentando '{lugar[2]}' en {RETRY_DELAY_SECONDS}s (intento {attempts_so_far}/{args.max_retries}).")
                    updated_lugar = lugar[:7] + (attempts_so_far,)
                    retry_tracker.schedule(q, updated_lugar, RETRY_DELAY_SECONDS)
                else:
                    tqdm.write(f"[{name}] '{lugar[2]}' agoto los {args.max_retries} intentos, queda como fallido definitivo.")
                    with pbar_lock:
                        stats["fallidos"] += 1
                        pbar.set_postfix(ok=stats["completados"], fallidos=stats["fallidos"], reviews=stats["reviews"])
                        pbar.update(1)
                # navegador probablemente en mal estado tras la excepcion -> reiniciar
                try:
                    scraper.__exit__(None, None, None)
                except Exception:
                    pass
                try:
                    scraper = nuevo_scraper(name, args.optimized_high_volume)
                except Exception as e_arranque:
                    # Si ni con reintentos arranca Chrome, este worker no puede seguir.
                    # Antes esto se escapaba del except y mataba al worker en silencio,
                    # dejando su parte de la cola sin procesar y terminando la corrida
                    # con 'pendiente=N'. Ahora se registra explicitamente.
                    logger.critical(f"[{name}] Worker abortado, Chrome no arranca: {e_arranque}")
                    tqdm.write(f"[{name}] WORKER ABORTADO: Chrome no arranca. Los museos restantes quedan pendientes y se retoman al relanzar.")
                    raise
                procesados_desde_reinicio = 0

            if args.pause > 0:
                time.sleep(args.pause)
    finally:
        try:
            scraper.__exit__(None, None, None)
        except Exception:
            pass


class RetryTracker:
    """Cuenta reintentos programados via threading.Timer que todavia no se
    re-encolaron, para que los workers sepan que no deben terminar aunque la
    cola este momentaneamente vacia."""

    def __init__(self):
        self._lock = threading.Lock()
        self._n = 0

    def count(self):
        with self._lock:
            return self._n

    def schedule(self, q, lugar, delay_seconds):
        with self._lock:
            self._n += 1

        def _requeue():
            q.put(lugar)
            with self._lock:
                self._n -= 1

        threading.Timer(delay_seconds, _requeue).start()


def run(args):
    conn = init_db(Path(args.db))
    load_museos_into_db(
        conn,
        Path(args.museos_csv),
        args.limit_museos,
        args.max_google_reviews,
    )

    pending = get_pending(conn, args.max_retries)
    total_pending = len(pending)
    logger.info(f"Museos pendientes de procesar en esta corrida: {total_pending}")
    print(f"Museos pendientes de procesar en esta corrida: {total_pending}")
    if total_pending == 0:
        logger.info("Nada pendiente. Corrida completa.")
        print("Nada pendiente. Corrida completa.")
        return

    q = queue_mod.Queue()
    for row in pending:
        q.put(row)

    raw_out = Path(args.out_raw)
    raw_out.parent.mkdir(parents=True, exist_ok=True)

    retry_tracker = RetryTracker()
    stats = {"completados": 0, "fallidos": 0, "reviews": 0}
    pbar = tqdm(total=total_pending, desc="Museos", unit="lugar")

    threads = [
        threading.Thread(target=worker, args=(f"w{i}", q, conn, raw_out, args, retry_tracker, pbar, stats), daemon=True)
        for i in range(args.concurrent)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    pbar.close()

    with db_lock:
        cur = conn.execute("SELECT status, COUNT(*) FROM museos GROUP BY status")
        resumen = ", ".join(f"{s}={c}" for s, c in cur.fetchall())
        logger.info("Resumen de estado final: " + resumen)
        print("Resumen de estado final: " + resumen)


def consolidate(args):
    """Consolida el CSV crudo de la Etapa 4-M en los entregables finales.

    Equivalente al `--consolidate-only` de run_full_reviews.py (Etapa 4 general), con
    tres diferencias deliberadas.

    Claves de join entre los tres archivos del pipeline:
        comentarios_museos_crudo.csv .google_place_id
          == base_museos_peru.csv    .id
          == estado_scraping_museos.db / museos.lugar_id

    Salidas (en data/resenas/):
        resenas_museos_consolidadas.csv       reseñas deduplicadas
        resenas_museos_consolidadas.parquet   idem, particionado por departamento
        cobertura_museos_por_lugar.csv        una fila por museo, con cobertura y banderas
    """
    raw_out = Path(args.out_raw)
    out_base = Path(args.out)
    try:
        reviews_df = load_consolidation_reviews(raw_out, out_base.with_suffix(".csv"))
    except FileNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)
    n_crudo = len(reviews_df)
    reviews_df = reviews_df.drop_duplicates(subset=["google_place_id", "id_review"])
    n_dups = n_crudo - len(reviews_df)

    # Solo lectura: la corrida de scraping puede estar escribiendo esta misma base.
    conn_ro = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True)
    try:
        museos_df = pd.read_sql("SELECT * FROM museos", conn_ro)
    finally:
        conn_ro.close()

    # Conteo real de filas escritas, no el contador que dejo el scraper.
    museos_df["n_reviews_obtenidas_real"] = (
        reviews_df.groupby("google_place_id").size()
        .reindex(museos_df["lugar_id"]).fillna(0).astype(int).values
    )
    # En modo sin tope (0) no existe un techo artificial que marcar.
    museos_df["techo_alcanzado"] = (
        args.max_reviews > 0
    ) & (museos_df["n_reviews_obtenidas_real"] >= args.max_reviews)

    # n_reviews_google viene de la columna `reviews` de la Etapa 2 (listado de
    # busqueda), que no es el techo real de lo que el panel del lugar sirve. Donde el
    # CSV dice 118, el panel sirve 29 y el scraper extrae las 29. Por eso esta columna
    # es una brecha entre dos conteos distintos, no reseñas perdidas.
    museos_df["brecha_vs_conteo_busqueda"] = (
        museos_df["n_reviews_google"].fillna(0) - museos_df["n_reviews_obtenidas_real"]
    ).clip(lower=0).astype(int)

    # Esta si es una señal honesta de que algo salio mal: el scraper dio el lugar por
    # completado pero no escribio ninguna reseña (regla DQ-10 del datamart).
    museos_df["sospechoso_cero_resenas"] = (
        (museos_df["status"] == "completado") & (museos_df["n_reviews_obtenidas_real"] == 0)
    )

    out_base.parent.mkdir(parents=True, exist_ok=True)

    size_mb = raw_out.stat().st_size / (1024 * 1024) if raw_out.exists() else 0
    if size_mb < 400 or out_base.with_suffix(".csv").exists():
        # Entregable para Excel en Windows: UTF-8 con BOM. El raw incremental
        # conserva UTF-8 simple porque se abre en append durante la corrida.
        reviews_df.to_csv(out_base.with_suffix(".csv"), index=False, encoding="utf-8-sig")
        logger.info(f"CSV consolidado escrito ({size_mb:.1f} MB crudo).")
    else:
        logger.warning(f"Archivo crudo de {size_mb:.0f} MB — se omite el .csv consolidado, "
                       f"solo se genera .parquet particionado por departamento.")

    parquet_dir = out_base.with_suffix(".parquet")
    if args.codigo_pais:
        # OneDrive puede dejar bloqueada una carpeta Parquet particionada aun
        # despues de cerrar Python. Para LATAM se usa un archivo plano,
        # idempotente y compatible con la consolidacion global.
        parquet_out = out_base.with_name(f"{out_base.name}_flat.parquet")
        reviews_df.to_parquet(parquet_out, index=False)
    else:
        # PerÃº conserva su salida histÃ³rica particionada y su comportamiento previo.
        if parquet_dir.exists():
            shutil.rmtree(parquet_dir)   # el particionado hace append: hay que limpiar antes
        reviews_df.to_parquet(parquet_dir, index=False, partition_cols=["departamento"])
        parquet_out = parquet_dir

    cobertura_out = Path(args.out_cobertura)
    cobertura_out.parent.mkdir(parents=True, exist_ok=True)
    museos_df.to_csv(cobertura_out, index=False, encoding="utf-8-sig")

    completados = int((museos_df["status"] == "completado").sum())
    sospechosos = int(museos_df["sospechoso_cero_resenas"].sum())
    resumen = (f"Consolidado: {len(reviews_df)} reseñas ({n_dups} duplicadas descartadas) "
               f"de {completados} museos completados -> {parquet_out.name}")
    logger.info(resumen)
    print(resumen)
    print(f"  cobertura por lugar -> {cobertura_out}")
    if sospechosos:
        # ASCII deliberado: PowerShell puede usar cp1252 aun cuando los CSV se
        # escriben correctamente en UTF-8 con BOM.
        print(f"  ADVERTENCIA: {sospechosos} museo(s) marcados 'completado' con 0 reseñas (revisar).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--country", "--codigo-pais", dest="codigo_pais", default=None,
                    help="Código ISO alpha-2; activa rutas aisladas (ej. MX).")
    ap.add_argument("--museos-csv", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--out-raw", default=None)
    ap.add_argument(
        "--max-reviews", type=int, default=30000, dest="max_reviews",
        help="Máximo por museo; 0 = sin tope, hasta que Google no entregue más reseñas (default: 30000).",
    )
    ap.add_argument("--sort-by", default="newest", choices=list(SORT_IND.keys()))
    ap.add_argument("--concurrent", type=int, default=3)
    ap.add_argument("--limit-museos", type=int, default=None,
                    help="Límite reproducible por ID; usar solo para pilotos.")
    ap.add_argument("--max-google-reviews", type=int, default=None,
                    help="Filtra por el proxy reviews de discovery; usar solo para pilotos rápidos.")
    ap.add_argument("--pause", type=float, default=0.0, help="Pausa fija (segundos) entre lugares por worker; sin aleatoriedad.")
    ap.add_argument("--optimized-high-volume", action="store_true",
                    help="Usa scroll podado e incremental para museos de alto volumen; compatible con SQLite y workers.")
    ap.add_argument("--high-volume-time-budget", type=int, default=0,
                    help="Segundos máximos por museo en modo optimizado; 0 = sin presupuesto global.")
    ap.add_argument("--high-volume-batch-timeout", type=int, default=180,
                    help="Corta un museo si una tanda optimizada tarda más de estos segundos.")
    ap.add_argument("--high-volume-sin-progreso", type=int, default=6,
                    help="Tandas optimizadas sin reseñas nuevas antes de considerar agotado el panel.")
    ap.add_argument("--max-retries", type=int, default=3)
    ap.add_argument("--restart-every", type=int, default=150, help="Reiniciar el navegador cada N museos por worker")
    ap.add_argument("--consolidate-only", action="store_true", dest="consolidate_only",
                    help="No scrapea: consolida el CSV crudo en los entregables finales.")
    ap.add_argument("--out", default=None,
                    help="Ruta base (sin extension) de la salida consolidada.")
    ap.add_argument("--out-cobertura", default=None,
                    help="CSV de cobertura por lugar; default: ruta del país.")
    args = ap.parse_args()

    if args.max_reviews < 0:
        ap.error("--max-reviews debe ser 0 o un entero positivo.")
    if args.high_volume_time_budget < 0 or args.high_volume_batch_timeout <= 0 or args.high_volume_sin_progreso <= 0:
        ap.error("Los parámetros de alto volumen deben ser positivos; el presupuesto admite 0 para no limitar.")

    country = resolve_country_args(args)
    if country is not None:
        logger.info(
            f"Modo LATAM: {country['pais']} ({country['codigo_pais']}); "
            f"estado={Path(args.db).name}, raw={Path(args.out_raw).name}"
        )

    t0 = time.time()
    if args.consolidate_only:
        consolidate(args)
        logger.info(f"Tiempo total de esta corrida: {time.time() - t0:.1f}s")
        print(f"Tiempo total de esta corrida: {time.time() - t0:.1f}s")
        return
    run(args)
    logger.info(f"Tiempo total de esta corrida: {time.time() - t0:.1f}s")
    print(f"Tiempo total de esta corrida: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
