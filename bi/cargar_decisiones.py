#!/usr/bin/env python3
"""Carga las decisiones de curaduría de lugares desde el Excel y (opcional) reconstruye la capa BI.

Uso:
  python3 cargar_decisiones.py lugares_dudosos.xlsx                    # SIMULACIÓN: valida y muestra el impacto, no escribe nada
  python3 cargar_decisiones.py lugares_dudosos.xlsx --aplicar          # escribe las decisiones (un lote auditable)
  python3 cargar_decisiones.py lugares_dudosos.xlsx --aplicar --reconstruir   # además reconstruye bi.* y verifica la reconciliación
  python3 cargar_decisiones.py --reconstruir                           # solo reconstruir (ejecuta 00 y 01) y verificar
  python3 cargar_decisiones.py decisiones_vigentes.csv --aplicar --reconstruir   # reproduce la curaduría vigente (el .xlsx también vale)

Conexión (administrador, con permiso de escritura en bi.*; no es el usuario del dashboard):
  MUSEOS_DB_HOST (127.0.0.1) MUSEOS_DB_PORT (14330) MUSEOS_ADMIN_USER (sa)
  MUSEOS_ADMIN_PASS  o  MUSEOS_ADMIN_PASS_FILE (ruta a un archivo con la contraseña)
Reglas:
  · Decisión vacía = no se toca ese lugar (si ya tenía una decisión previa, se conserva).
  · 'Mantener' explícito se registra (sirve para deshacer un Excluir/Reclasificar previo).
  · Un error de validación aborta todo el lote; las advertencias no.
"""
import argparse, hashlib, os, re, sys, unicodedata
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
import pymssql
try:
    from openpyxl import load_workbook
except ImportError:  # solo hace falta para leer .xlsx
    load_workbook = None

HOJA = "Lugares dudosos"
DEC = {"mantener": "Mantener", "excluir": "Excluir", "reclasificar": "Reclasificar"}
MAX_EXCL_PCT = 5.0  # salvaguarda: más de este % de reseñas excluidas exige --forzar


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().casefold()


def conectar():
    pw = os.getenv("MUSEOS_ADMIN_PASS")
    if not pw and os.getenv("MUSEOS_ADMIN_PASS_FILE"):
        f = Path(os.environ["MUSEOS_ADMIN_PASS_FILE"])
        if f.exists():
            pw = f.read_text().strip()
    if not pw:
        sys.exit("Falta la contraseña de administrador: defina MUSEOS_ADMIN_PASS o MUSEOS_ADMIN_PASS_FILE.")
    return pymssql.connect(os.getenv("MUSEOS_DB_HOST", "127.0.0.1"), os.getenv("MUSEOS_ADMIN_USER", "sa"), pw,
                           "MuseosLatam_Datamart", port=int(os.getenv("MUSEOS_DB_PORT", "14330")), timeout=0)


def leer_csv(ruta):
    """Mismo contenido que la hoja 'Lugares dudosos' (columnas por nombre), en CSV UTF-8. Es el formato de bi/decisiones_vigentes.csv."""
    import csv
    req = {"id": "ID lugar", "lugar": "Lugar", "cat_actual": "Categoría actual", "cat_sug": "Categoría sugerida",
           "decision": "DECISIÓN", "cat_nueva": "NUEVA CATEGORÍA", "comentario": "COMENTARIO"}
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        cab = {norm(k): k for k in (rd.fieldnames or [])}
        falta = [v for v in req.values() if norm(v) not in cab]
        if falta:
            sys.exit("Faltan columnas en el CSV: " + ", ".join(falta))
        filas = []
        for n, r in enumerate(rd, start=2):
            g = lambda k: (r.get(cab[norm(req[k])]) or "").strip() or None
            if g("id") is None and g("lugar") is None:
                continue
            filas.append({"fila": n, **{k: g(k) for k in req}})
    return filas


def leer_excel(ruta):
    if str(ruta).lower().endswith(".csv"):
        return leer_csv(ruta)
    wb = load_workbook(ruta, data_only=True, read_only=True)
    if HOJA not in wb.sheetnames:
        sys.exit(f"El archivo no tiene la hoja '{HOJA}'.")
    it = wb[HOJA].iter_rows(values_only=True)
    cab = {norm(v): i for i, v in enumerate(next(it)) if v is not None}
    req = {"id": "ID lugar", "lugar": "Lugar", "cat_actual": "Categoría actual", "cat_sug": "Categoría sugerida",
           "decision": "DECISIÓN", "cat_nueva": "NUEVA CATEGORÍA", "comentario": "COMENTARIO"}
    falta = [v for v in req.values() if norm(v) not in cab]
    if falta:
        sys.exit("Faltan columnas en la hoja: " + ", ".join(falta))
    filas = []
    for n, r in enumerate(it, start=2):
        g = lambda k: r[cab[norm(req[k])]] if cab[norm(req[k])] < len(r) else None
        if g("id") is None and g("lugar") is None:
            continue
        filas.append({"fila": n, **{k: g(k) for k in req}})
    return filas


def a_int(v):
    try:
        if isinstance(v, str):
            v = v.strip()
        f = float(v)
        return int(f) if f == int(f) else None
    except (TypeError, ValueError):
        return None


def validar(filas, cur):
    """Devuelve (decisiones_validas, errores, advertencias)."""
    cur.execute("SELECT categoria FROM bi.categoria_valida")
    validas = {norm(r[0]): r[0] for r in cur.fetchall()}
    cur.execute("SELECT l.sk_lugar,l.nombre,l.categoria_normalizada,CASE WHEN EXISTS(SELECT 1 FROM mart.fact_resena f WHERE f.sk_lugar=l.sk_lugar) THEN 1 ELSE 0 END FROM mart.dim_lugar l")
    db = {int(r[0]): (r[1], r[2], r[3]) for r in cur.fetchall()}
    errores, avisos, ok, vistos = [], [], [], {}
    for f in filas:
        n = f["fila"]
        sk = a_int(f["id"])
        raw = f["decision"]
        if raw is None or str(raw).strip() == "":
            f["vacia"] = True
            if sk is not None:
                ok.append({**f, "sk": sk, "decision": None})
            continue
        if sk is None:
            errores.append(f"Fila {n}: 'ID lugar' no es un entero ({f['id']!r}).")
            continue
        if sk in vistos:
            errores.append(f"Fila {n}: el ID {sk} está repetido (también en la fila {vistos[sk]}).")
            continue
        vistos[sk] = n
        if sk not in db:
            errores.append(f"Fila {n}: el ID {sk} no existe en mart.dim_lugar.")
            continue
        nom, cat_db, tiene_res = db[sk]
        if norm(f["lugar"] or "") != norm(nom):
            errores.append(f"Fila {n}: el nombre no coincide con el ID {sk} (Excel: {f['lugar']!r} / base: {nom!r}). ¿Se ordenó solo una parte de las columnas?")
            continue
        d = DEC.get(norm(raw))
        if d is None:
            errores.append(f"Fila {n} (ID {sk}): decisión no válida {raw!r}; use Mantener, Excluir o Reclasificar.")
            continue
        if not tiene_res:
            avisos.append(f"Fila {n} (ID {sk}): el lugar no tiene reseñas; la decisión no tendrá efecto en el dashboard.")
        if f["cat_actual"] is not None and norm(f["cat_actual"]) != norm(cat_db):
            avisos.append(f"Fila {n} (ID {sk}): la 'Categoría actual' del Excel ({f['cat_actual']}) difiere de la del datamart ({cat_db}).")
        nueva = None
        cn = (str(f["cat_nueva"]).strip() if f["cat_nueva"] else "")
        cs = (str(f["cat_sug"]).strip() if f["cat_sug"] else "")
        if d == "Reclasificar":
            elegida = cn or cs
            if not elegida:
                errores.append(f"Fila {n} (ID {sk}): 'Reclasificar' sin 'NUEVA CATEGORÍA' ni categoría sugerida.")
                continue
            if norm(elegida) not in validas:
                errores.append(f"Fila {n} (ID {sk}): categoría {elegida!r} no válida; permitidas: {', '.join(sorted(validas.values()))}.")
                continue
            nueva = validas[norm(elegida)]
            if not cn:
                avisos.append(f"Fila {n} (ID {sk}): sin 'NUEVA CATEGORÍA'; se usó la sugerida ({nueva}).")
            if norm(nueva) == norm(cat_db):
                avisos.append(f"Fila {n} (ID {sk}): la nueva categoría es igual a la actual; se registra como 'Mantener'.")
                d, nueva = "Mantener", None
        elif cn:
            avisos.append(f"Fila {n} (ID {sk}): hay 'NUEVA CATEGORÍA' pero la decisión es {d}; se ignora la categoría.")
        com = (str(f["comentario"]).strip() if f["comentario"] else None) or None
        if com and len(com) > 1000:
            avisos.append(f"Fila {n} (ID {sk}): comentario truncado a 1000 caracteres.")
            com = com[:1000]
        ok.append({**f, "sk": sk, "decision": d, "categoria_nueva": nueva, "comentario": com, "nombre": nom, "categoria_original": cat_db})
    return ok, errores, avisos


def resenas_por_lugar(cur, ids):
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 800):
        lote = ",".join(str(int(x)) for x in ids[i:i + 800])
        cur.execute(f"SELECT sk_lugar,COUNT_BIG(*) FROM mart.fact_resena WHERE sk_lugar IN ({lote}) GROUP BY sk_lugar")
        out.update({int(a): int(b) for a, b in cur.fetchall()})
    return out


def ejecutar_script(conn, ruta):
    sql = Path(ruta).read_text(encoding="utf-8")
    cur = conn.cursor()
    for lote in re.split(r"(?im)^\s*GO\s*$", sql):
        if lote.strip():
            cur.execute(lote)
            try:
                while cur.nextset():
                    pass
            except Exception:
                pass


def reconstruir():
    conn = conectar()
    conn.autocommit(True)
    for s in ("00_decisiones_setup.sql", "01_bi_setup.sql"):
        print(f"  ejecutando {s} ...", flush=True)
        ejecutar_script(conn, HERE / s)
    cur = conn.cursor(as_dict=True)
    cur.execute("SELECT * FROM bi.v_control_reconciliacion")
    c = cur.fetchone()
    print("\nControl de reconciliación:")
    for k in ("resenas_datamart", "resenas_excluidas", "resenas_bi", "menciones_datamart", "menciones_excluidas", "menciones_bi", "decisiones_huerfanas"):
        print(f"  {k:24s}{c[k]:>12,}")
    print(f"  {'OK':24s}{'sí' if c['ok'] == 1 else 'NO  <-- REVISAR'}")
    cur.execute("SELECT sk_lugar,decision,nombre_lugar,motivo FROM bi.v_decision_huerfana")
    for r in cur.fetchall():
        print("  decisión huérfana:", r)
    conn.close()
    return c["ok"] == 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("excel", nargs="?")
    ap.add_argument("--aplicar", action="store_true", help="escribe las decisiones (por defecto solo simula)")
    ap.add_argument("--reconstruir", action="store_true", help="reconstruye la capa BI y verifica la reconciliación")
    ap.add_argument("--forzar", action="store_true", help=f"permite excluir más de {MAX_EXCL_PCT}% de las reseñas")
    a = ap.parse_args()
    if not a.excel and not a.reconstruir:
        ap.error("indique un archivo Excel y/o --reconstruir")
    if a.aplicar and not a.excel:
        ap.error("--aplicar requiere el archivo Excel")
    if a.excel:
        ruta = Path(a.excel)
        if not ruta.exists():
            sys.exit(f"No existe {ruta}")
        sha = hashlib.sha256(ruta.read_bytes()).hexdigest()
        conn = conectar()
        cur = conn.cursor()
        cur.execute("IF OBJECT_ID('bi.lugar_decision') IS NULL SELECT 0 ELSE SELECT 1")
        if not cur.fetchone()[0]:
            sys.exit("Faltan las tablas de decisiones: ejecute antes  python3 cargar_decisiones.py --reconstruir")
        filas = leer_excel(ruta)
        ok, errores, avisos = validar(filas, cur)
        print(f"Archivo: {ruta.name}  (sha256 {sha[:12]}…)  filas leídas: {len(filas)}")
        con_dec = [x for x in ok if x["decision"]]
        print(f"Filas con decisión: {len(con_dec)}  ·  sin decisión: {len(ok) - len(con_dec)}")
        if avisos:
            print(f"\nAdvertencias ({len(avisos)}):")
            for m in avisos[:25]:
                print("  -", m)
            if len(avisos) > 25:
                print(f"  … y {len(avisos) - 25} más")
        if errores:
            print(f"\nERRORES ({len(errores)}) — no se escribió nada:")
            for m in errores[:40]:
                print("  x", m)
            if len(errores) > 40:
                print(f"  … y {len(errores) - 40} más")
            sys.exit(2)
        cur.execute("SELECT sk_lugar,decision,categoria_nueva,comentario FROM bi.lugar_decision")
        previas = {int(r[0]): (r[1], r[2], r[3]) for r in cur.fetchall()}
        cambios, solo_com = [], []
        for x in con_dec:
            p = previas.get(x["sk"])
            if p is None or p[0] != x["decision"] or p[1] != x["categoria_nueva"]:
                cambios.append(x)
            elif (p[2] or None) != x["comentario"]:
                solo_com.append(x)
        conservadas = [x for x in ok if not x["decision"] and x["sk"] in previas]
        if conservadas:
            print(f"\nNota: {len(conservadas)} filas sin decisión conservan su decisión previa.")
        cur.execute("SELECT COUNT_BIG(*) FROM mart.fact_resena")
        total = cur.fetchone()[0]
        excl_final = {sk for sk, p in previas.items() if p[0] == "Excluir"}
        for x in cambios:
            (excl_final.add if x["decision"] == "Excluir" else excl_final.discard)(x["sk"])
        rl = resenas_por_lugar(cur, {x["sk"] for x in cambios} | excl_final)
        pct = 100 * sum(rl.get(s, 0) for s in excl_final) / total
        print("\nResumen del archivo:", dict(Counter(x["decision"] for x in con_dec)))
        print(f"Cambios respecto del estado actual: {len(cambios)}  (solo comentario: {len(solo_com)})")
        trans = Counter((x["categoria_original"], x["categoria_nueva"]) for x in cambios if x["decision"] == "Reclasificar")
        for (o, n_), c in trans.most_common():
            print(f"    reclasificar {o} -> {n_}: {c}")
        top = sorted((x for x in cambios if x["decision"] == "Excluir"), key=lambda x: -rl.get(x["sk"], 0))[:8]
        for x in top:
            print(f"    excluir  {rl.get(x['sk'], 0):>6,} reseñas  {x['nombre']}")
        print(f"Reseñas excluidas tras aplicar: {sum(rl.get(s, 0) for s in excl_final):,} de {total:,} ({pct:.2f} %)  ·  lugares excluidos: {len(excl_final)}")
        if pct > MAX_EXCL_PCT and not a.forzar:
            sys.exit(f"Se excluiría más de {MAX_EXCL_PCT}% de las reseñas; revise el archivo o repita con --forzar.")
        if not a.aplicar:
            print("\nSIMULACIÓN: no se escribió nada. Repita con --aplicar para guardar.")
        elif not cambios and not solo_com:
            print("\nSin cambios que aplicar: el estado ya coincide con el archivo (no se crea un lote).")
        else:
            conn.autocommit(False)
            try:
                cnt = Counter(x["decision"] for x in con_dec)
                cur.execute("INSERT bi.decision_lote(archivo,sha256,filas_con_decision,n_excluir,n_reclasificar,n_mantener,n_cambios) OUTPUT INSERTED.id_lote VALUES (%s,%s,%d,%d,%d,%d,%d)",
                            (ruta.name, sha, len(con_dec), cnt["Excluir"], cnt["Reclasificar"], cnt["Mantener"], len(cambios)))
                lote = int(cur.fetchone()[0])
                for x in cambios + solo_com:
                    p = previas.get(x["sk"])
                    if x in cambios:
                        cur.execute("INSERT bi.lugar_decision_hist(sk_lugar,decision_anterior,categoria_anterior,decision_nueva,categoria_nueva,comentario,id_lote) VALUES (%d,%s,%s,%s,%s,%s,%d)",
                                    (x["sk"], p[0] if p else None, p[1] if p else None, x["decision"], x["categoria_nueva"], x["comentario"], lote))
                    cur.execute("""MERGE bi.lugar_decision AS t USING (SELECT %d AS sk_lugar) s ON t.sk_lugar=s.sk_lugar
                                   WHEN MATCHED THEN UPDATE SET decision=%s,categoria_nueva=%s,comentario=%s,id_lote=%d,actualizado_utc=SYSUTCDATETIME()
                                   WHEN NOT MATCHED THEN INSERT(sk_lugar,decision,categoria_nueva,categoria_original,nombre_lugar,comentario,id_lote)
                                        VALUES(%d,%s,%s,%s,%s,%s,%d);""",
                                (x["sk"], x["decision"], x["categoria_nueva"], x["comentario"], lote,
                                 x["sk"], x["decision"], x["categoria_nueva"], x["categoria_original"], x["nombre"], x["comentario"], lote))
                conn.commit()
                print(f"\nAPLICADO: lote #{lote} ({len(cambios)} cambios). Las vistas del dashboard cambian al ejecutar con --reconstruir.")
            except Exception:
                conn.rollback()
                raise
        conn.close()
    if a.reconstruir:
        print("\nReconstruyendo la capa BI …")
        if not reconstruir():
            sys.exit(3)
        print("Listo. Reinicie el dashboard para que cargue los nuevos datos.")


if __name__ == "__main__":
    main()
