"""validar_conteos.py — ¿Cuantas reseñas hay REALMENTE disponibles por museo?

Contrasta tres numeros distintos que suelen confundirse:

  1. base   : columna `reviews` de base_museos_peru.csv. Viene del LISTADO DE BUSQUEDA
              de la Etapa 2 (mapScraper). Es un agregado de Google.
  2. panel  : el conteo que Google muestra en la CABECERA del panel de reseñas del
              lugar, leido del navegador en vivo. Es lo que Google dice tener ahi.
  3. servido: cuantas reseñas entrega efectivamente el panel al hacer scroll hasta
              agotarlo. Es el techo real de extraccion.

La sospecha a validar es que base > panel > servido, es decir que la columna `reviews`
promete mucho mas de lo que el panel de lugar puede entregar.

Uso:
  python3 validar_conteos.py --n 15                  # muestra estratificada
  python3 validar_conteos.py --solo-masivos --n 8    # solo lugares de alto volumen
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
from selenium.webdriver.common.by import By

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "repos" / "googlemaps-reviews-scraper-es"))

JS_SCROLL = """
const d = document.querySelector('div.m6QErb.DxyBCb.kA9KIf.dS8AEf');
if (d) { d.scrollTop = d.scrollHeight; return 1; } return -1;
"""
JS_CONTAR = "return document.querySelectorAll('div.jftiEf').length;"
JS_PODAR = """
const b = document.querySelectorAll('div.jftiEf');
let n = 0;
for (let i = 0; i < arguments[0] && i < b.length; i++) { if (b[i].parentNode) { b[i].remove(); n++; } }
return n;
"""

# La cabecera del panel: se buscan varios contenedores y se toma el primero que
# contenga un conteo de opiniones. Los selectores de Google cambian sin aviso.
SELECTORES_CABECERA = ["div.jANrlb", "div.F7nice", "div.fontBodySmall", "div.PPCwl"]
# El numero va pegado a "opiniones". No admitir espacios ni saltos dentro del numero:
# el bloque de cabecera trae "3,6\n155 opiniones" y un patron laxo capturaba "36155".
RE_CONTEO = re.compile(r"(\d[\d.,]*)\s*(?:opiniones|opinión|reseñas|reviews)", re.I)


def leer_panel(driver):
    """Devuelve el conteo declarado por Google en la cabecera del panel, o None."""
    for sel in SELECTORES_CABECERA:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel)[:4]:
                m = RE_CONTEO.search(el.text or "")
                if m:
                    return int(re.sub(r"[^\d]", "", m.group(1)))
        except Exception:
            continue
    return None


def medir(sc, fila, tope, budget, prune=True):
    """Scrollea hasta agotar el panel y devuelve (panel_declara, servido)."""
    if sc.sort_by(fila.url_place, 1) != 0:
        return None, -1
    panel = leer_panel(sc.driver)

    t0, procesados, vistos, vacias = time.time(), 0, 0, 0
    while vistos < tope and time.time() - t0 < budget:
        sc.driver.execute_script(JS_SCROLL)
        time.sleep(0.6)
        n = sc.driver.execute_script(JS_CONTAR)
        nuevos = n - procesados
        if nuevos <= 0:
            vacias += 1
            if vacias >= 8:
                break
            continue
        vacias = 0
        vistos += nuevos
        procesados = n
        if prune and procesados > 400:
            procesados -= sc.driver.execute_script(JS_PODAR, procesados - 200)
    return panel, vistos


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--tope", type=int, default=30000)
    ap.add_argument("--budget", type=int, default=420, help="Segundos por lugar.")
    ap.add_argument("--solo-masivos", action="store_true", dest="solo_masivos")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "data" / "resenas" / "_validacion_conteos.csv"))
    args = ap.parse_args()

    b = pd.read_csv(PROJECT_ROOT / "data" / "lugares" / "base_museos_peru.csv")
    b = b[b.reviews.notna()]

    if args.solo_masivos:
        muestra = b.nlargest(args.n, "reviews")
    else:
        # estratificada: cubre todo el rango de volumen, no solo los grandes
        b = b.assign(_tramo=pd.cut(b.reviews, [0, 10, 50, 200, 1000, 5000, 10**9],
                                   labels=["1-10", "11-50", "51-200", "201-1k", "1k-5k", ">5k"]))
        por = max(1, args.n // 6)
        muestra = b.groupby("_tramo", observed=True).apply(
            lambda g: g.sample(min(por, len(g)), random_state=11)).reset_index(drop=True)

    print("=" * 88)
    print(f"  VALIDACION DE CONTEOS — {len(muestra)} museos | tope {args.tope:,} | {args.budget}s c/u")
    print("=" * 88)
    print(f"{'museo':<44}{'base':>8}{'panel':>8}{'servido':>9}{'srv/base':>10}")
    print("-" * 88)

    from googlemaps import GoogleMapsScraper
    sc = GoogleMapsScraper(debug=False, turbo=True)
    filas = []
    try:
        for _, r in muestra.iterrows():
            try:
                panel, servido = medir(sc, r, args.tope, args.budget)
            except Exception as e:
                panel, servido = None, -1
                print(f"  ! {str(e)[:60]}")
            ratio = f"{100*servido/r.reviews:.1f}%" if servido and servido > 0 and r.reviews else "—"
            print(f"{str(r.title)[:43]:<44}{r.reviews:>8.0f}"
                  f"{(panel if panel is not None else -1):>8}{servido:>9}{ratio:>10}", flush=True)
            filas.append({"id": r.id, "museo": r.title, "categoria": r.category,
                          "base_reviews": r.reviews, "panel_declara": panel,
                          "panel_sirve": servido})
    finally:
        try:
            sc.__exit__(None, None, None)
        except Exception:
            pass

    df = pd.DataFrame(filas)
    df.to_csv(args.out, index=False)
    print("-" * 88)
    v = df[df.panel_sirve > 0]
    if len(v):
        print(f"  servido/base   : mediana {100*(v.panel_sirve/v.base_reviews).median():.1f}%")
        p = v[v.panel_declara.notna() & (v.panel_declara > 0)]
        if len(p):
            print(f"  panel/base     : mediana {100*(p.panel_declara/p.base_reviews).median():.1f}%")
            print(f"  servido/panel  : mediana {100*(p.panel_sirve/p.panel_declara).median():.1f}%")
    print(f"  -> {args.out}")


if __name__ == "__main__":
    main()
