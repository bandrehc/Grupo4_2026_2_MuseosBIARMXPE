"""scrape_qorikancha.py — Extractor dedicado para lugares de volumen muy alto.

Por qué existe
--------------
Qorikancha (78 520 reseñas reportadas) es el unico lugar del corpus que rompe a
scrape_comentarios_museos.py. Dos corridas fallaron:

  tope 30000 -> 21.8 h, renderer al 106% de CPU, RSS clavado en 1979 MB, 0 reseñas
  tope  5000 ->  2.6 h, renderer al 107% de CPU, RSS clavado en 1169 MB, 0 reseñas

Medido con /proc: en 120 s el proceso Python leyo *0 bytes* de chromedriver. No es
lentitud, es estancamiento dentro de una sola llamada al navegador.

CAUSA RAIZ: get_reviews() de googlemaps.py hace, EN CADA TANDA de 10 reseñas, tres
operaciones que recorren el DOM COMPLETO:

  1. find_elements(REVIEW_BLOCK_CSS)          -> escanea todo el DOM
  2. __expand_reviews()                       -> find_elements + un execute_script
                                                 POR CADA boton de todo el DOM
  3. BeautifulSoup(driver.page_source)        -> serializa y reparsea la pagina entera

Con N reseñas cargadas el costo por tanda es O(N), y el total O(N^2). Para los demas
museos N tope ~1160 y no se nota. Para Qorikancha N crece sin limite y Chrome termina
gastando todo su tiempo escaneando un DOM gigante en vez de cargar reseñas nuevas.

QUE HACE DISTINTO ESTE SCRIPT
-----------------------------
  - Extrae solo los bloques nuevos, via un unico execute_script que devuelve su
    outerHTML. Nunca pide page_source ni escanea el DOM completo.
  - Expande el texto solo de los bloques nuevos, no de todos.
  - Escribe cada tanda al CSV al instante: si se corta, lo extraido ya esta en disco.
  - Presupuesto de tiempo global y por tanda: aborta en vez de colgarse.
  - turbo=True: sin imagenes, page_load_strategy eager -> mucha menos RAM y CPU.
  - --prune: elimina del DOM los bloques ya procesados. Ataca la causa raiz de frente
    (mantiene el DOM chico), a costa de que el scroll pueda comportarse distinto.

Escribe a un CSV PROPIO. Nunca toca el corpus general: el append se hace aparte y
solo tras validar.
"""
import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRAPER_DIR = PROJECT_ROOT / "repos" / "googlemaps-reviews-scraper-es"
sys.path.insert(0, str(SCRAPER_DIR))

REVIEW_FIELDS = [
    "google_place_id", "nombre_lugar", "categoria_google", "distrito", "provincia",
    "departamento", "id_review", "caption", "relative_date", "review_date",
    "retrieval_date", "rating", "username", "n_review_user", "url_user", "url_source",
]

SORT_IND = {"most_relevant": 0, "newest": 1, "highest_rating": 2, "lowest_rating": 3}

# Una sola llamada: expande y devuelve el outerHTML de los bloques a partir de `start`.
JS_EXPANDIR = """
const bloques = document.querySelectorAll('div.jftiEf');
for (let i = arguments[0]; i < bloques.length; i++) {
  const b = bloques[i].querySelector('button.w8nwRe.kyuRq');
  if (b) b.click();
}
return bloques.length;
"""

JS_EXTRAER = """
const bloques = document.querySelectorAll('div.jftiEf');
const salida = [];
for (let i = arguments[0]; i < bloques.length; i++) salida.push(bloques[i].outerHTML);
return salida;
"""

# Saca del DOM los bloques ya procesados para que no vuelva a escanearlos.
JS_PODAR = """
const bloques = document.querySelectorAll('div.jftiEf');
let n = 0;
for (let i = 0; i < arguments[0] && i < bloques.length; i++) {
  if (bloques[i].parentNode) { bloques[i].remove(); n++; }
}
return n;
"""

JS_SCROLL = """
const d = document.querySelector('div.m6QErb.DxyBCb.kA9KIf.dS8AEf');
if (d) { d.scrollTop = d.scrollHeight; return d.scrollHeight; }
return -1;
"""


def escribir(out_csv: Path, filas):
    if not filas:
        return
    nuevo = not (out_csv.exists() and out_csv.stat().st_size > 0)
    with open(out_csv, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
        if nuevo:
            w.writeheader()
        for f in filas:
            w.writerow(f)
        fh.flush()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nombre", default="Qorikancha")
    ap.add_argument("--max-reviews", type=int, default=5000, dest="max_reviews")
    ap.add_argument("--sort-by", default="newest", choices=list(SORT_IND.keys()))
    ap.add_argument("--out", default=str(PROJECT_ROOT / "data" / "resenas" / "_qorikancha_tmp.csv"))
    ap.add_argument("--time-budget", type=int, default=2700, dest="time_budget",
                    help="Segundos totales antes de cortar y quedarse con lo extraido.")
    ap.add_argument("--batch-timeout", type=int, default=180, dest="batch_timeout",
                    help="Si una tanda tarda mas que esto, se corta.")
    ap.add_argument("--sin-progreso", type=int, default=6, dest="sin_progreso",
                    help="Tandas seguidas sin reseñas nuevas antes de cortar.")
    ap.add_argument("--prune", action="store_true",
                    help="Eliminar del DOM los bloques ya procesados (ataca la causa raiz).")
    ap.add_argument("--turbo", action="store_true", default=True)
    args = ap.parse_args()

    museos = pd.read_csv(PROJECT_ROOT / "data" / "lugares" / "base_museos_peru.csv")
    fila = museos[museos.title == args.nombre]
    if fila.empty:
        sys.exit(f"No se encontro '{args.nombre}' en base_museos_peru.csv")
    m = fila.iloc[0]

    out_csv = Path(args.out)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 68)
    print(f"  {m.title}  ({m.id})")
    print(f"  reportadas por Google: {m.reviews:,.0f}   tope: {args.max_reviews:,}")
    print(f"  turbo={args.turbo}  prune={args.prune}  presupuesto={args.time_budget}s")
    print(f"  salida: {out_csv.name}")
    print("=" * 68, flush=True)

    from googlemaps import GoogleMapsScraper
    sc = GoogleMapsScraper(debug=False, turbo=args.turbo)
    parse = sc._GoogleMapsScraper__parse

    t0 = time.time()
    total, vacias, procesados = 0, 0, 0
    vistos = set()

    try:
        if sc.sort_by(m.url_place, SORT_IND[args.sort_by]) != 0:
            print("Error: sort_by fallo: no se pudo abrir el panel de reseñas.")
            return 1
        print(f"[{time.time()-t0:6.0f}s] panel abierto, empezando extraccion", flush=True)

        tanda = 0
        while total < args.max_reviews:
            if time.time() - t0 > args.time_budget:
                print(f"\n⏱ Presupuesto de {args.time_budget}s agotado. Se conserva lo extraido.")
                break

            tb = time.time()
            tanda += 1

            sc.driver.execute_script(JS_SCROLL)
            time.sleep(1.2)                       # deja que cargue el lote nuevo
            sc.driver.execute_script(JS_EXPANDIR, procesados)
            time.sleep(0.4)                       # deja que se expanda el texto
            htmls = sc.driver.execute_script(JS_EXTRAER, procesados)

            dur = time.time() - tb
            if dur > args.batch_timeout:
                print(f"\n⏱ Tanda {tanda} tardo {dur:.0f}s (> {args.batch_timeout}s). Se corta.")
                break

            if not htmls:
                vacias += 1
                if vacias >= args.sin_progreso:
                    print(f"\n{vacias} tandas seguidas sin reseñas nuevas: se agoto el panel.")
                    break
                continue

            filas = []
            for h in htmls:
                bloque = BeautifulSoup(h, "html.parser").find("div", class_="jftiEf")
                if bloque is None:
                    continue
                r = parse(bloque)
                rid = r.get("id_review")
                if not rid or rid in vistos:
                    continue
                vistos.add(rid)
                r.update({
                    "google_place_id": m.id, "nombre_lugar": m.title,
                    "categoria_google": m.category, "distrito": m.distrito_final,
                    "provincia": m.provincia_final, "departamento": m.departamento_final,
                    "url_source": m.url_place,
                })
                filas.append(r)

            procesados += len(htmls)

            if filas:
                escribir(out_csv, filas)          # <- en disco YA, no al final
                total += len(filas)
                vacias = 0
            else:
                vacias += 1
                if vacias >= args.sin_progreso:
                    print(f"\n{vacias} tandas sin reseñas nuevas: se agoto el panel.")
                    break

            if args.prune and procesados > 400:
                podados = sc.driver.execute_script(JS_PODAR, procesados - 200)
                procesados -= podados

            if tanda % 10 == 0 or dur > 10:
                print(f"[{time.time()-t0:6.0f}s] tanda {tanda:4d} | +{len(filas):3d} | "
                      f"total {total:5d} | {dur:5.1f}s/tanda", flush=True)

    except KeyboardInterrupt:
        print("\nInterrumpido. Lo extraido ya esta en disco.")
    except Exception as e:
        print(f"\nError: {type(e).__name__}: {str(e)[:200]}")
        print("  Lo extraido hasta el fallo ya esta en disco.")
    finally:
        try:
            sc.__exit__(None, None, None)
        except Exception:
            pass

    print("=" * 68)
    print(f"  RESULTADO: {total} reseñas en {time.time()-t0:.0f}s -> {out_csv}")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
