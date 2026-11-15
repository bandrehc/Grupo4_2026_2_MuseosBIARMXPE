"""scrape_museos_ii.py — Corrida II: extraccion rapida de reseñas.

Universo: los 581 museos de data/lugares/base_museos_peru.csv que se sumaron al ampliar
el filtro de category=="Museo" exacto a toda categoria que contenga "museo" (se pasa con
--museos-csv; el lote intermedio no se versiona porque esta contenido en base_museos_peru.csv).
Salida propia: data/resenas/comentarios_museos_crudo-II.csv. No toca la corrida I.

Por qué es más rápido que scrape_comentarios_museos.py
------------------------------------------------------
El cuello de botella del scraper original esta en get_reviews() de googlemaps.py, que
en CADA tanda de 10 reseñas recorre el DOM completo tres veces:

    find_elements(REVIEW_BLOCK_CSS)        -> escanea todo el DOM
    __expand_reviews()                     -> un execute_script POR CADA boton del DOM
    BeautifulSoup(driver.page_source)      -> serializa y reparsea la pagina entera

Con N reseñas cargadas eso cuesta O(N) por tanda y O(N^2) en total. Es lo que colgo a
Qorikancha 21,8 h sin extraer una fila.

Aca se usa el enfoque validado en scrape_qorikancha.py, generalizado a todos los lugares:

  - Un unico execute_script devuelve el outerHTML solo de los bloques nuevos.
    Nunca se pide page_source ni se escanea el DOM entero.
  - Se expande solo el texto de los bloques nuevos.
  - --prune saca del DOM los bloques ya procesados, manteniendolo chico.
  - turbo: sin imagenes y page_load_strategy eager.
  - Escritura incremental POR TANDA: si un lugar se corta, lo extraido ya esta en disco.
  - Presupuesto de tiempo por lugar: ningun lugar puede colgar la corrida.
"""
import argparse
import csv
import logging
import queue as queue_mod
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRAPER_DIR = PROJECT_ROOT / "repos" / "googlemaps-reviews-scraper-es"
sys.path.insert(0, str(SCRAPER_DIR))

DEFAULT_MUSEOS_CSV = PROJECT_ROOT / "data" / "lugares" / "base_museos_delta_II.csv"
DEFAULT_DB = PROJECT_ROOT / "logs" / "estado_scraping_museos_II.db"
DEFAULT_RAW_OUT = PROJECT_ROOT / "data" / "resenas" / "comentarios_museos_crudo-II.csv"

REVIEW_FIELDS = [
    "google_place_id", "nombre_lugar", "categoria_google", "distrito", "provincia",
    "departamento", "id_review", "caption", "relative_date", "review_date",
    "retrieval_date", "rating", "username", "n_review_user", "url_user", "url_source",
]

SORT_IND = {"most_relevant": 0, "newest": 1, "highest_rating": 2, "lowest_rating": 3}

JS_EXPANDIR = """
const b = document.querySelectorAll('div.jftiEf');
for (let i = arguments[0]; i < b.length; i++) {
  const x = b[i].querySelector('button.w8nwRe.kyuRq'); if (x) x.click();
}
return b.length;
"""
JS_EXTRAER = """
const b = document.querySelectorAll('div.jftiEf');
const o = [];
for (let i = arguments[0]; i < b.length; i++) o.push(b[i].outerHTML);
return o;
"""
JS_PODAR = """
const b = document.querySelectorAll('div.jftiEf');
let n = 0;
for (let i = 0; i < arguments[0] && i < b.length; i++) { if (b[i].parentNode) { b[i].remove(); n++; } }
return n;
"""
JS_SCROLL = """
const d = document.querySelector('div.m6QErb.DxyBCb.kA9KIf.dS8AEf');
if (d) { d.scrollTop = d.scrollHeight; return 1; } return -1;
"""

import re as _re
from selenium.webdriver.common.by import By as _By

# Conteo que Google muestra en la cabecera del panel de reseñas. Validado el 2026-09-02:
# coincide EXACTAMENTE con lo que el panel entrega al agotar el scroll (155=155, 142=142,
# 25=25, 8=8, 89=89 en la muestra), y difiere mucho de la columna `reviews` de la base.
# El numero va pegado a "opiniones"; no admitir espacios dentro del numero evita capturar
# el rating de la linea previa ("3,6\n155 opiniones" daba 36155).
_RE_CONTEO = _re.compile(r"(\d[\d.,]*)\s*(?:opiniones|opinión|reseñas|reviews)", _re.I)
_SEL_CABECERA = ["div.jANrlb", "div.F7nice", "div.fontBodySmall", "div.PPCwl"]


def leer_panel(driver):
    """Conteo declarado por Google en la cabecera del panel, o None si no se pudo leer."""
    for sel in _SEL_CABECERA:
        try:
            for el in driver.find_elements(_By.CSS_SELECTOR, sel)[:4]:
                m = _RE_CONTEO.search(el.text or "")
                if m:
                    return int(_re.sub(r"[^\d]", "", m.group(1)))
        except Exception:
            continue
    return None


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[logging.FileHandler(
        PROJECT_ROOT / "logs" / f"scrape_ii_{datetime.now():%Y%m%d_%H%M%S}.log", encoding="utf-8")],
)
logger = logging.getLogger("scrape_museos_ii")

db_lock = threading.Lock()
csv_lock = threading.Lock()
pbar_lock = threading.Lock()


def init_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cn = sqlite3.connect(str(db_path), check_same_thread=False)
    cn.execute("""CREATE TABLE IF NOT EXISTS museos (
        lugar_id TEXT PRIMARY KEY, url_place TEXT, nombre TEXT, categoria_google TEXT,
        distrito TEXT, provincia TEXT, departamento TEXT, n_reviews_google INTEGER,
        status TEXT NOT NULL DEFAULT 'pendiente', attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT, n_reviews_obtenidas INTEGER, panel_declara INTEGER, segundos REAL,
        started_at TEXT, completed_at TEXT)""")
    cn.commit()
    return cn


def cargar(cn, csv_path: Path):
    df = pd.read_csv(csv_path)
    filas = [(r["id"], r["url_place"], r["title"], r["category"], r["distrito_final"],
              r["provincia_final"], r["departamento_final"],
              int(r["reviews"]) if pd.notna(r["reviews"]) else None) for _, r in df.iterrows()]
    with db_lock:
        cn.executemany("INSERT OR IGNORE INTO museos (lugar_id,url_place,nombre,categoria_google,"
                       "distrito,provincia,departamento,n_reviews_google) VALUES (?,?,?,?,?,?,?,?)", filas)
        cn.commit()
    return len(filas)


def pendientes(cn, max_retries):
    with db_lock:
        return cn.execute(
            "SELECT lugar_id,url_place,nombre,categoria_google,distrito,provincia,departamento,attempts "
            "FROM museos WHERE status IN ('pendiente','en_progreso') "
            "OR (status = 'fallido' AND attempts < ?) ORDER BY lugar_id",
            (max_retries,)).fetchall()


def marcar(cn, lugar_id, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    with db_lock:
        cn.execute(f"UPDATE museos SET {sets} WHERE lugar_id=?", (*kw.values(), lugar_id))
        cn.commit()


def escribir(out: Path, filas):
    if not filas:
        return
    with csv_lock:
        nuevo = not (out.exists() and out.stat().st_size > 0)
        with open(out, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
            if nuevo:
                w.writeheader()
            for f in filas:
                w.writerow(f)


def nuevo_scraper(name, turbo, intentos=5):
    from googlemaps import GoogleMapsScraper
    err = None
    for i in range(1, intentos + 1):
        try:
            sc = GoogleMapsScraper(debug=False, turbo=turbo)
            sc.__enter__()
            # Por defecto Selenium corta un execute_script a los 30s. Con el panel muy
            # cargado, extraer/expandir tarda mas y salta "script timeout" — la causa de
            # 20 de los 24 fallos de la corrida III.
            sc.driver.set_script_timeout(300)
            return sc
        except Exception as e:
            err = e
            logger.error(f"[{name}] Chrome no arranco ({i}/{intentos}): {e}")
            time.sleep(min(10 * i, 60))
    raise RuntimeError(f"[{name}] Chrome no arranco: {err}")


def extraer(sc, lugar, args, out_raw, progreso=None):
    """Extrae un lugar recorriendo VARIOS ordenamientos y unificando el resultado.

    Google limita cuan profundo se puede scrollear el panel para un orden dado, pero
    cada orden expone un subconjunto DISTINTO de la misma bolsa de reseñas. Medido en
    Museo Pachacamac: newest 390, most_relevant 370, highest_rating 216, lowest_rating
    216 -> union 780, el doble de lo que da el mejor orden solo.

    El set `vistos` es compartido entre pasadas, asi que una reseña ya capturada en una
    pasada anterior no se reescribe. Devuelve (n, estado, panel).
    """
    lugar_id, url, nombre, cat, dist, prov, depto, _ = lugar
    parse = sc._GoogleMapsScraper__parse

    vistos = set()
    total = 0
    panel = None
    t0 = time.time()
    ordenes = [o.strip() for o in args.sort_passes.split(",") if o.strip()]

    for i_orden, orden in enumerate(ordenes):
        if time.time() - t0 > args.place_budget:
            return total, "parcial", panel

        if sc.sort_by(url, SORT_IND[orden]) != 0:
            if i_orden == 0:
                raise RuntimeError("sort_by_failed")
            continue          # un orden que no abre no invalida los ya recorridos
        if panel is None:
            panel = leer_panel(sc.driver)

        procesados, vacias = 0, 0
        while total < args.max_reviews:
            if time.time() - t0 > args.place_budget:
                return total, "parcial", panel

            sc.driver.execute_script(JS_SCROLL)
            time.sleep(args.settle)
            sc.driver.execute_script(JS_EXPANDIR, procesados)
            time.sleep(args.expand_wait)
            htmls = sc.driver.execute_script(JS_EXTRAER, procesados)

            if not htmls:
                vacias += 1
                if vacias >= args.sin_progreso:
                    break
                continue

            filas = []
            for h in htmls:
                blo = BeautifulSoup(h, "html.parser").find("div", class_="jftiEf")
                if blo is None:
                    continue
                r = parse(blo)
                rid = r.get("id_review")
                if not rid or rid in vistos:
                    continue
                vistos.add(rid)
                r.update({"google_place_id": lugar_id, "nombre_lugar": nombre,
                          "categoria_google": cat, "distrito": dist, "provincia": prov,
                          "departamento": depto, "url_source": url})
                filas.append(r)

            procesados += len(htmls)
            if filas:
                escribir(out_raw, filas)      # en disco YA
                total += len(filas)
                if progreso is not None:
                    progreso["n"] = total
                vacias = 0
            else:
                vacias += 1
                if vacias >= args.sin_progreso:
                    break

            if args.prune and procesados > args.prune_cada:
                procesados -= sc.driver.execute_script(JS_PODAR, procesados - args.prune_deja)

    # Cero reseñas extraidas siempre es un fallo, nunca un exito. No depende de ninguna
    # cifra externa: el conteo del panel se descarto como referencia. Si un lugar de
    # verdad no tiene reseñas, agotara sus reintentos y quedara 'fallido', que es la
    # descripcion honesta. Marcarlo "completado" lo sacaria de la cola para siempre.
    if total == 0:
        raise RuntimeError("no entrego ninguna reseña en ningun ordenamiento")

    return total, "completado", panel


def worker(name, q, cn, args, tracker, pbar, stats):
    desde_reinicio = 0
    sc = nuevo_scraper(name, args.turbo)
    try:
        while True:
            try:
                lugar = q.get(timeout=5)
            except Exception:
                if tracker.count() == 0:
                    return
                continue

            lid = lugar[0]
            marcar(cn, lid, status="en_progreso", started_at=datetime.now(timezone.utc).isoformat())
            with db_lock:
                cn.execute("UPDATE museos SET attempts=attempts+1 WHERE lugar_id=?", (lid,)); cn.commit()
            t0 = time.time()
            progreso = {"n": 0}
            try:
                if desde_reinicio >= args.restart_every:
                    sc.__exit__(None, None, None); sc = nuevo_scraper(name, args.turbo); desde_reinicio = 0

                n, estado, panel = extraer(sc, lugar, args, Path(args.out_raw), progreso)
                dur = time.time() - t0
                marcar(cn, lid, status=estado, n_reviews_obtenidas=n, panel_declara=panel, segundos=round(dur, 1),
                       completed_at=datetime.now(timezone.utc).isoformat(), last_error=None)
                desde_reinicio += 1
                with pbar_lock:
                    stats["ok"] += 1; stats["reviews"] += n; stats["seg"] += dur
                    pbar.set_postfix(ok=stats["ok"], fall=stats["fall"], rev=stats["reviews"])
                    pbar.update(1)
            except Exception as e:
                dur = time.time() - t0
                rescatadas = progreso["n"]
                logger.error(f"[{name}] FALLO '{lugar[2]}' tras {rescatadas} reseñas: {str(e)[:130]}")
                # Si alcanzo a extraer algo, el lugar quedo PARCIAL, no fallido: sus datos
                # ya estan en disco y volver a empezar de cero solo los reescribiria.
                marcar(cn, lid, status=("parcial" if rescatadas > 0 else "fallido"),
                       n_reviews_obtenidas=(rescatadas or None), last_error=str(e)[:400],
                       segundos=round(dur, 1), completed_at=datetime.now(timezone.utc).isoformat())
                if rescatadas == 0 and lugar[7] + 1 < args.max_retries:
                    tracker.schedule(q, lugar[:7] + (lugar[7] + 1,), args.retry_delay)
                else:
                    with pbar_lock:
                        stats["fall"] += 1
                        pbar.set_postfix(ok=stats["ok"], fall=stats["fall"], rev=stats["reviews"])
                        pbar.update(1)
                try:
                    sc.__exit__(None, None, None)
                except Exception:
                    pass
                sc = nuevo_scraper(name, args.turbo); desde_reinicio = 0
    finally:
        try:
            sc.__exit__(None, None, None)
        except Exception:
            pass


class Tracker:
    def __init__(self):
        self._l = threading.Lock(); self._n = 0
    def count(self):
        with self._l: return self._n
    def schedule(self, q, lugar, delay):
        with self._l: self._n += 1
        def _re():
            q.put(lugar)
            with self._l: self._n -= 1
        threading.Timer(delay, _re).start()


def run(args):
    cn = init_db(Path(args.db))
    cargar(cn, Path(args.museos_csv))
    pend = pendientes(cn, args.max_retries)
    print(f"Museos pendientes: {len(pend)}  |  concurrencia={args.concurrent} turbo={args.turbo} "
          f"prune={args.prune} tope={args.max_reviews}")
    if not pend:
        print("Nada pendiente."); return

    q = queue_mod.Queue()
    for r in pend:
        q.put(r)
    Path(args.out_raw).parent.mkdir(parents=True, exist_ok=True)

    tracker = Tracker()
    stats = {"ok": 0, "fall": 0, "reviews": 0, "seg": 0.0}
    pbar = tqdm(total=len(pend), desc="Museos II", unit="lugar")
    hilos = [threading.Thread(target=worker, args=(f"w{i}", q, cn, args, tracker, pbar, stats),
                              daemon=True) for i in range(args.concurrent)]
    t0 = time.time()
    for t in hilos: t.start()
    for t in hilos: t.join()
    pbar.close()
    el = time.time() - t0

    with db_lock:
        res = ", ".join(f"{s}={c}" for s, c in cn.execute(
            "SELECT status, COUNT(*) FROM museos GROUP BY status"))
    print(f"\nEstado final: {res}")
    print(f"Rendimiento: {stats['reviews']} reseñas en {el:.0f}s "
          f"= {60*stats['reviews']/max(el,1):.1f} reseñas/min | "
          f"{60*(stats['ok']+stats['fall'])/max(el,1):.1f} museos/min")
    logger.info(f"Estado final: {res} | {60*stats['reviews']/max(el,1):.1f} reseñas/min")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--museos-csv", default=str(DEFAULT_MUSEOS_CSV))
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out-raw", default=str(DEFAULT_RAW_OUT))
    ap.add_argument("--max-reviews", type=int, default=3000, dest="max_reviews")
    ap.add_argument("--sort-passes", default="newest,most_relevant,highest_rating,lowest_rating",
                    dest="sort_passes",
                    help="Ordenamientos a recorrer por lugar, separados por coma. Cada uno\nexpone reseñas distintas; la union duplica el rendimiento.")
    ap.add_argument("--concurrent", type=int, default=4)
    ap.add_argument("--max-retries", type=int, default=3, dest="max_retries")
    ap.add_argument("--retry-delay", type=int, default=60, dest="retry_delay",
                    help="Segundos antes de reintentar un lugar que fallo.")
    ap.add_argument("--restart-every", type=int, default=60, dest="restart_every")
    ap.add_argument("--place-budget", type=int, default=600, dest="place_budget",
                    help="Segundos maximos por lugar; al superarlo se marca 'parcial'.")
    ap.add_argument("--settle", type=float, default=1.0, help="Espera tras el scroll.")
    ap.add_argument("--expand-wait", type=float, default=0.3, dest="expand_wait")
    ap.add_argument("--sin-progreso", type=int, default=4, dest="sin_progreso")
    ap.add_argument("--prune", action="store_true", default=True)
    ap.add_argument("--prune-cada", type=int, default=150, dest="prune_cada",
                    help="Podar el DOM cuando haya mas de N bloques acumulados.")
    ap.add_argument("--prune-deja", type=int, default=100, dest="prune_deja",
                    help="Bloques a conservar tras podar.")
    ap.add_argument("--no-prune", action="store_false", dest="prune")
    ap.add_argument("--turbo", action="store_true", default=True)
    ap.add_argument("--no-turbo", action="store_false", dest="turbo")
    args = ap.parse_args()
    t0 = time.time()
    run(args)
    print(f"Tiempo total: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
