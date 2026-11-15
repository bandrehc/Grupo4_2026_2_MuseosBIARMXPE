"""scrape_museos_v2.py — Extraccion de reseñas orientada a INTEGRIDAD y velocidad (Argentina).

Evolucion de scrape_museos_ii.py (corridas II-IV de Peru). Mantiene el esquema de 16
columnas del contrato historico y la clave google_place_id + id_review, pero cambia tres
cosas:

1. INTEGRIDAD MEDIBLE. El conteo que Google declara en la cabecera del panel
   (`panel_declara`) es el denominador. Por cada lugar se guarda `cobertura =
   obtenidas / panel_declara`. Un lugar solo es 'completado' si cobertura >= --cob-min;
   si no, queda 'parcial' y se REANUDA (sin reescribir lo ya extraido) en la siguiente
   pasada. Las reseñas sin comentario (solo estrellas) se cuentan igual: el bloque
   `div.jftiEf` existe con o sin texto y `caption` queda vacio.
2. VELOCIDAD. Espera adaptativa (se sondea el DOM hasta que aparezcan bloques nuevos en
   vez de dormir tiempos fijos) y parada anticipada: si el primer ordenamiento ya
   alcanza el panel, no se recorren los otros tres (en Peru siempre se hacian 4 pasadas).
3. REANUDACION EXACTA. Los id_review ya capturados se guardan en SQLite
   (tabla `ids`); un lugar parcial retomado arranca con ese conjunto y solo escribe lo nuevo.

Estados: pendiente | en_progreso | completado | parcial | fallido | sin_resenas.
`sin_resenas` = la ficha cargo (h1 presente) pero no tiene pestaña de opiniones y asi
se confirmo en todos los intentos: es un resultado valido, no un fallo.
"""
import argparse
import csv
import logging
import queue as queue_mod
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "repos" / "googlemaps-reviews-scraper-es"))

REVIEW_FIELDS = [
    "google_place_id", "nombre_lugar", "categoria_google", "distrito", "provincia",
    "departamento", "id_review", "caption", "relative_date", "review_date",
    "retrieval_date", "rating", "username", "n_review_user", "url_user", "url_source",
]
SORT_IND = {"default": None, "most_relevant": 0, "newest": 1, "highest_rating": 2, "lowest_rating": 3}

JS_N = "return document.querySelectorAll('div.jftiEf').length;"
JS_SCROLL = """
const d = document.querySelector('div.m6QErb.DxyBCb.kA9KIf.dS8AEf');
if (d) { d.scrollTop = d.scrollHeight; return 1; } return -1;
"""
JS_NUDGE = """
const d = document.querySelector('div.m6QErb.DxyBCb.kA9KIf.dS8AEf');
if (d) { d.scrollTop = Math.max(0, d.scrollHeight - 1500); } return 1;
"""
JS_EXPANDIR = """
const b = document.querySelectorAll('div.jftiEf'); let c = 0;
for (let i = arguments[0]; i < b.length; i++) {
  const x = b[i].querySelector('button.w8nwRe.kyuRq'); if (x) { x.click(); c++; }
}
return c;
"""
JS_EXTRAER = """
const b = document.querySelectorAll('div.jftiEf'); const o = [];
for (let i = arguments[0]; i < b.length; i++) o.push(b[i].outerHTML);
return o;
"""
JS_PODAR = """
const b = document.querySelectorAll('div.jftiEf'); let n = 0;
for (let i = 0; i < arguments[0] && i < b.length; i++) { if (b[i].parentNode) { b[i].remove(); n++; } }
return n;
"""

# El numero va pegado a "opiniones"; no admitir espacios dentro del numero evita capturar
# el rating de la linea previa ("3,6\n155 opiniones" daba 36155).
_RE_CONTEO = re.compile(r"(\d[\d.,]*)\s*(?:opiniones|opinión|opinion|reseñas|reseña|reviews|review)", re.I)
_SEL_CABECERA = ["div.jANrlb", "div.F7nice", "div.fontBodySmall", "div.PPCwl"]


def leer_panel(driver):
    """Conteo declarado por Google en la cabecera del panel, o None si no se pudo leer."""
    for sel in _SEL_CABECERA:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel)[:6]:
                m = _RE_CONTEO.search(el.text or "")
                if m:
                    return int(re.sub(r"[^\d]", "", m.group(1)))
        except Exception:
            continue
    return None


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[logging.FileHandler(PROJECT_ROOT / "logs" / f"scrape_v2_{datetime.now():%Y%m%d_%H%M%S}.log",
                                  encoding="utf-8")],
)
logger = logging.getLogger("scrape_museos_v2")

db_lock = threading.Lock()
csv_lock = threading.Lock()
pbar_lock = threading.Lock()


def init_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cn = sqlite3.connect(str(db_path), check_same_thread=False)
    cn.execute("PRAGMA journal_mode=WAL")
    cn.execute("""CREATE TABLE IF NOT EXISTS museos (
        lugar_id TEXT PRIMARY KEY, url_place TEXT, nombre TEXT, categoria_google TEXT,
        distrito TEXT, provincia TEXT, departamento TEXT, n_reviews_google INTEGER,
        status TEXT NOT NULL DEFAULT 'pendiente', attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT, n_reviews_obtenidas INTEGER, panel_declara INTEGER, cobertura REAL,
        n_sin_texto INTEGER, pasadas TEXT, segundos REAL, started_at TEXT, completed_at TEXT)""")
    cn.execute("CREATE TABLE IF NOT EXISTS ids (lugar_id TEXT, id_review TEXT, PRIMARY KEY (lugar_id, id_review))")
    cn.commit()
    return cn


def cargar(cn, csv_path: Path):
    df = pd.read_csv(csv_path)
    filas = [(r["id"], r["url_place"], r["title"], r["category"], r.get("distrito_final"),
              r.get("provincia_final"), r.get("departamento_final"),
              int(r["reviews"]) if pd.notna(r["reviews"]) else None) for _, r in df.iterrows()]
    with db_lock:
        cn.executemany("INSERT OR IGNORE INTO museos (lugar_id,url_place,nombre,categoria_google,"
                       "distrito,provincia,departamento,n_reviews_google) VALUES (?,?,?,?,?,?,?,?)", filas)
        cn.commit()
    return len(filas)


def pendientes(cn, max_retries, orden="chicos_primero"):
    """Cola: pendientes/en_progreso y fallidos/parciales con intentos disponibles.

    Orden por tamaño declarado en la busqueda (proxy de popularidad): los lugares chicos
    primero maximizan museos completos por hora; los masivos van al final con presupuesto
    largo. Los de conteo desconocido (casi siempre sin reseñas) van al final de todo.
    """
    with db_lock:
        rows = cn.execute(
            "SELECT lugar_id,url_place,nombre,categoria_google,distrito,provincia,departamento,attempts "
            "FROM museos WHERE status IN ('pendiente','en_progreso') "
            "OR (status IN ('fallido','parcial') AND attempts < ?) "
            + ("ORDER BY (COALESCE(panel_declara, n_reviews_google) IS NULL), COALESCE(panel_declara, n_reviews_google, 0), lugar_id"
               if orden == "chicos_primero" else
               "ORDER BY (COALESCE(panel_declara, n_reviews_google) IS NULL), COALESCE(panel_declara, n_reviews_google, 0) DESC, lugar_id"),
            (max_retries,)).fetchall()
    return rows


def marcar(cn, lugar_id, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    with db_lock:
        cn.execute(f"UPDATE museos SET {sets} WHERE lugar_id=?", (*kw.values(), lugar_id))
        cn.commit()


def ids_previos(cn, lugar_id):
    with db_lock:
        return {r[0] for r in cn.execute("SELECT id_review FROM ids WHERE lugar_id=?", (lugar_id,))}


def guardar_ids(cn, lugar_id, rids):
    with db_lock:
        cn.executemany("INSERT OR IGNORE INTO ids VALUES (?,?)", [(lugar_id, r) for r in rids])
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
            w.writerows(filas)


def perfil_worker(name):
    """Clona el perfil base con sesion (--perfil) a un directorio propio del trabajador.

    Chrome bloquea un user-data-dir por proceso, asi que cada trabajador usa su copia.
    """
    base = PERFIL_BASE.get("dir")
    if not base:
        return None
    import shutil
    # Clones en disco local (ext4): el perfil base vive en NTFS/FUSE y Chrome tarda minutos en arrancar alli.
    dst = Path.home() / ".cache" / "ar_perfiles" / f"{Path(base).name}_{name}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copytree(base, dst, ignore=shutil.ignore_patterns("Singleton*", "Cache", "Code Cache", "GPUCache"))
    # Un scraper matado (o un Chrome caido) deja candados que impiden arrancar de nuevo: son propios del trabajador.
    for lock in dst.glob("Singleton*"):
        try:
            lock.unlink()
        except OSError:
            pass
    return str(dst)


PERFIL_BASE = {"dir": None}


def nuevo_scraper(name, turbo, intentos=5):
    from googlemaps import GoogleMapsScraper
    err = None
    for i in range(1, intentos + 1):
        try:
            sc = GoogleMapsScraper(debug=False, turbo=turbo, user_data_dir=perfil_worker(name))
            sc.__enter__()
            sc.driver.set_script_timeout(300)
            sc.driver.set_window_size(1366, 1400)  # viewport alto: Maps solo renderiza tarjetas visibles
            return sc
        except Exception as e:
            err = e
            logger.error(f"[{name}] Chrome no arranco ({i}/{intentos}): {e}")
            time.sleep(min(10 * i, 60))
    raise RuntimeError(f"[{name}] Chrome no arranco: {err}")


def esperar_nuevos(driver, n_antes, timeout):
    """Sondea el DOM hasta que haya mas bloques que `n_antes`. True si aparecieron."""
    fin = time.time() + timeout
    while time.time() < fin:
        if driver.execute_script(JS_N) > n_antes:
            return True
        time.sleep(0.08)
    return False


def sin_panel_confirmado(driver):
    """True si la ficha cargo (h1 presente) pero no existe pestaña de opiniones.

    Experimento 2026-10-16: en Argentina las fichas sin reseñas a veces no muestran el boton
    "Escribir una opinión" (p. ej. plazas, monumentos), asi que ya no se exige. Para no
    confundirla con una ficha a medio cargar se reevalua tras una espera corta.
    """
    def _sin_tab():
        if not driver.find_elements(By.CSS_SELECTOR, "h1.DUwDvf"):
            return False
        tabs = driver.find_elements(By.XPATH, '//button[@role="tab"]')
        return not any(("pinion" in (t.text or "") or "eseñ" in (t.text or "")) for t in tabs)
    try:
        if not _sin_tab():
            return False
        time.sleep(3)
        return _sin_tab()
    except Exception:
        return False


def abrir_sin_orden(sc, url):
    """Abre la pestaña de opiniones SIN cambiar el ordenamiento (el orden se hace en el analisis).

    Equivale a GoogleMapsScraper.sort_by menos el clic en el menu de orden. 0 = ok, -1 = fallo.
    """
    import googlemaps as gm
    sc._seen_ids.clear()
    sc.driver.get(url.strip())
    sc._GoogleMapsScraper__click_on_cookie_agreement()
    wait = gm.WebDriverWait(sc.driver, gm.MAX_WAIT)
    if not sc._GoogleMapsScraper__open_reviews_tab(wait):
        return -1
    # Sin el clic de ordenar, Maps no renderiza las tarjetas hasta que se hace scroll en el panel.
    d = sc.driver
    fin = time.time() + gm.REVIEWS_READY_TIMEOUT
    while time.time() < fin:
        if d.execute_script(JS_N):
            return 0
        d.execute_script(JS_SCROLL)
        time.sleep(1.0)
    return -1


def recorrer_orden(sc, args, parse, lugar, vistos, estado, out_raw, cn, t0):
    """Scrollea un ordenamiento hasta agotarlo (o alcanzar el panel). Muta `vistos` y `estado`."""
    lugar_id, url, nombre, cat, dist, prov, depto, _ = lugar
    d = sc.driver
    procesados, vacias = 0, 0
    while True:
        if estado["panel"] and len(vistos) >= estado["panel"]:
            return "panel_alcanzado"
        if time.time() - t0 > args.place_budget:
            return "presupuesto"

        n_antes = d.execute_script(JS_N)
        d.execute_script(JS_SCROLL)
        crecio = esperar_nuevos(d, n_antes, args.load_wait)
        if not crecio:
            d.execute_script(JS_NUDGE); time.sleep(0.3); d.execute_script(JS_SCROLL)
            crecio = esperar_nuevos(d, n_antes, args.load_wait)
        if crecio:
            if d.execute_script(JS_EXPANDIR, procesados):
                time.sleep(args.expand_wait)
        htmls = d.execute_script(JS_EXTRAER, procesados)

        filas, rids = [], []
        for h in htmls:
            blo = BeautifulSoup(h, "html.parser").find("div", class_="jftiEf")
            if blo is None:
                continue
            r = parse(blo)
            rid = r.get("id_review")
            if not rid or rid in vistos:
                continue
            vistos.add(rid); rids.append(rid)
            r.update({"google_place_id": lugar_id, "nombre_lugar": nombre, "categoria_google": cat,
                      "distrito": dist, "provincia": prov, "departamento": depto, "url_source": url})
            if not r.get("caption"):
                estado["sin_texto"] += 1
            filas.append(r)

        procesados += len(htmls)
        if filas:
            escribir(out_raw, filas)          # primero a disco...
            guardar_ids(cn, lugar_id, rids)   # ...luego el indice de reanudacion
            estado["progreso"] = len(vistos)
            vacias = 0
        else:
            vacias += 1
            if vacias >= args.sin_progreso:
                return "agotado"

        if args.prune and procesados > args.prune_cada:
            procesados -= d.execute_script(JS_PODAR, procesados - args.prune_deja)


def extraer(sc, lugar, args, out_raw, cn, estado):
    """Extrae un lugar. Devuelve (status, n_total, panel, pasadas_str)."""
    lugar_id, url = lugar[0], lugar[1]
    parse = sc._GoogleMapsScraper__parse
    vistos = ids_previos(cn, lugar_id)
    estado["progreso"] = len(vistos)
    estado.setdefault("sin_texto", 0)
    estado["panel"] = None
    t0 = time.time()
    pasadas = []

    for i_orden, orden in enumerate([o.strip() for o in args.sort_passes.split(",") if o.strip()]):
        if time.time() - t0 > args.place_budget:
            break
        abierto = abrir_sin_orden(sc, url) if orden == "default" else sc.sort_by(url, SORT_IND[orden])
        if abierto != 0:
            if i_orden == 0:
                if sin_panel_confirmado(sc.driver):
                    raise LookupError("sin_pestana_opiniones")
                raise RuntimeError("panel_no_cargo")
            continue
        if estado["panel"] is None:
            estado["panel"] = leer_panel(sc.driver)
        antes = len(vistos)
        motivo = recorrer_orden(sc, args, parse, lugar, vistos, estado, out_raw, cn, t0)
        pasadas.append(f"{orden}:+{len(vistos) - antes}:{motivo}")
        if motivo == "panel_alcanzado":
            break
        if estado["panel"] and len(vistos) >= estado["panel"] * args.cob_min:
            break                  # cobertura suficiente: no hace falta otro ordenamiento
        if estado["panel"] is None and i_orden >= 1:
            break                  # sin referencia: dos ordenamientos bastan
        if motivo == "presupuesto":
            break

    n = len(vistos)
    if n == 0:
        raise RuntimeError("no entrego ninguna reseña en ningun ordenamiento")
    panel = estado["panel"]
    cob = (n / panel) if panel else None
    ok = (panel is None and n > 0) or (cob is not None and cob >= args.cob_min)
    return ("completado" if ok else "parcial"), n, panel, ";".join(pasadas)


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
            estado = {"progreso": 0, "panel": None, "sin_texto": 0}
            try:
                if desde_reinicio >= args.restart_every:
                    sc.__exit__(None, None, None); sc = nuevo_scraper(name, args.turbo); desde_reinicio = 0
                status, n, panel, pasadas = extraer(sc, lugar, args, Path(args.out_raw), cn, estado)
                dur = time.time() - t0
                with db_lock:
                    previo = cn.execute("SELECT segundos FROM museos WHERE lugar_id=?", (lid,)).fetchone()[0] or 0
                marcar(cn, lid, status=status, n_reviews_obtenidas=n, panel_declara=panel,
                       cobertura=(round(n / panel, 4) if panel else None), n_sin_texto=estado["sin_texto"],
                       pasadas=pasadas, segundos=round(dur + previo, 1),
                       completed_at=datetime.now(timezone.utc).isoformat(), last_error=None)
                desde_reinicio += 1
                # un parcial con intentos disponibles vuelve a la cola para continuar
                if status == "parcial" and lugar[7] + 1 < args.max_retries:
                    tracker.schedule(q, lugar[:7] + (lugar[7] + 1,), args.retry_delay)
                else:
                    with pbar_lock:
                        stats["ok"] += 1; stats["reviews"] += n
                        pbar.set_postfix(ok=stats["ok"], fall=stats["fall"], rev=stats["reviews"]); pbar.update(1)
            except LookupError as e:
                marcar(cn, lid, status="sin_resenas", last_error=str(e), n_reviews_obtenidas=0,
                       segundos=round(time.time() - t0, 1), completed_at=datetime.now(timezone.utc).isoformat())
                if lugar[7] + 1 < args.max_retries:
                    # una ficha sin pestaña puede ser un fallo de carga: se confirma con reintentos
                    marcar(cn, lid, status="fallido")
                    tracker.schedule(q, lugar[:7] + (lugar[7] + 1,), args.retry_delay)
                else:
                    with pbar_lock:
                        stats["ok"] += 1; pbar.update(1)
            except Exception as e:
                rescatadas = estado["progreso"]
                logger.error(f"[{name}] FALLO '{lugar[2]}' tras {rescatadas} reseñas: {str(e)[:130]}")
                marcar(cn, lid, status=("parcial" if rescatadas > 0 else "fallido"),
                       n_reviews_obtenidas=(rescatadas or None), panel_declara=estado["panel"],
                       last_error=str(e)[:400], segundos=round(time.time() - t0, 1),
                       completed_at=datetime.now(timezone.utc).isoformat())
                if lugar[7] + 1 < args.max_retries:
                    tracker.schedule(q, lugar[:7] + (lugar[7] + 1,), args.retry_delay)
                else:
                    with pbar_lock:
                        stats["fall"] += 1
                        pbar.set_postfix(ok=stats["ok"], fall=stats["fall"], rev=stats["reviews"]); pbar.update(1)
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
        with self._l:
            return self._n

    def schedule(self, q, lugar, delay):
        with self._l:
            self._n += 1

        def _re():
            q.put(lugar)
            with self._l:
                self._n -= 1
        t = threading.Timer(delay, _re); t.daemon = True; t.start()


def run(args):
    cn = init_db(Path(args.db))
    cargar(cn, Path(args.museos_csv))
    pend = pendientes(cn, args.max_retries, args.orden)
    if args.limit:
        pend = pend[:args.limit]
    print(f"Museos pendientes: {len(pend)} | concurrencia={args.concurrent} turbo={args.turbo} "
          f"pasadas={args.sort_passes} cob_min={args.cob_min} budget={args.place_budget}s", flush=True)
    if not pend:
        print("Nada pendiente."); return
    q = queue_mod.Queue()
    for r in pend:
        q.put(r)
    Path(args.out_raw).parent.mkdir(parents=True, exist_ok=True)
    tracker = Tracker()
    stats = {"ok": 0, "fall": 0, "reviews": 0}
    pbar = tqdm(total=len(pend), desc="Museos", unit="lugar", mininterval=30)
    hilos = [threading.Thread(target=worker, args=(f"w{i}", q, cn, args, tracker, pbar, stats), daemon=True)
             for i in range(args.concurrent)]
    t0 = time.time()
    for t in hilos:
        t.start()
    for t in hilos:
        t.join()
    pbar.close()
    el = time.time() - t0
    with db_lock:
        res = ", ".join(f"{s}={c}" for s, c in cn.execute("SELECT status, COUNT(*) FROM museos GROUP BY status"))
    print(f"\nEstado final: {res}")
    print(f"Rendimiento: {stats['reviews']} reseñas (de lugares cerrados) en {el:.0f}s", flush=True)
    logger.info(f"Estado final: {res}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pais", default="ar", help="sufijo de archivos (default ar)")
    ap.add_argument("--museos-csv", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--out-raw", default=None)
    ap.add_argument("--sort-passes", default="default", dest="sort_passes",
                    help="Ordenes a recorrer, separados por coma. 'default' = sin ordenar (orden por defecto de Google); "
                         "ademas: newest,most_relevant,lowest_rating,highest_rating. Si la cobertura no alcanza, pasa al siguiente.")
    ap.add_argument("--concurrent", type=int, default=4)
    ap.add_argument("--max-retries", type=int, default=4, dest="max_retries")
    ap.add_argument("--retry-delay", type=int, default=30, dest="retry_delay")
    ap.add_argument("--restart-every", type=int, default=40, dest="restart_every")
    ap.add_argument("--place-budget", type=int, default=10800, dest="place_budget",
                    help="Segundos maximos por lugar y por intento; al superarlo queda 'parcial' y se reanuda.")
    ap.add_argument("--cob-min", type=float, default=0.97, dest="cob_min",
                    help="Cobertura (obtenidas/panel) minima para marcar 'completado'.")
    ap.add_argument("--load-wait", type=float, default=6.0, dest="load_wait")
    ap.add_argument("--expand-wait", type=float, default=0.15, dest="expand_wait")
    ap.add_argument("--sin-progreso", type=int, default=3, dest="sin_progreso")
    ap.add_argument("--prune-cada", type=int, default=150, dest="prune_cada")
    ap.add_argument("--prune-deja", type=int, default=100, dest="prune_deja")
    ap.add_argument("--no-prune", action="store_false", dest="prune", default=True)
    ap.add_argument("--no-turbo", action="store_false", dest="turbo", default=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--orden", choices=["chicos_primero", "grandes_primero"], default="chicos_primero",
                    help="Orden de la cola segun reseñas declaradas. grandes_primero maximiza reseñas por hora.")
    ap.add_argument("--perfil", default=None, help="Perfil de Chrome con sesion de Google iniciada (ver login_google.py). Sin sesion Maps entrega solo 5 reseñas por lugar.")
    args = ap.parse_args()
    p = args.pais.lower()
    PERFIL_BASE["dir"] = args.perfil
    args.museos_csv = args.museos_csv or str(PROJECT_ROOT / "data" / "lugares" / f"base_museos_{p}.csv")
    args.db = args.db or str(PROJECT_ROOT / "logs" / f"estado_scraping_museos_{p}.db")
    args.out_raw = args.out_raw or str(PROJECT_ROOT / "data" / "resenas" / f"comentarios_museos_crudo_{p}.csv")
    t0 = time.time()
    run(args)
    print(f"Tiempo total: {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
