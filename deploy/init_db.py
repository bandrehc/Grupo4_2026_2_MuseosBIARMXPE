#!/usr/bin/env python3
"""Inicializa la base para el dashboard (idempotente): restaura los .bak si faltan, crea el usuario de solo lectura,
conserva las columnas existentes, ejecuta bi/00_decisiones_setup.sql y bi/01_bi_setup.sql, carga bi/decisiones_vigentes.csv si no hay decisiones y verifica la reconciliación. El backup recibido ya está depurado; no se repiten migraciones destructivas.

Variables: MUSEOS_DB_HOST, MUSEOS_DB_PORT, MUSEOS_ADMIN_USER (sa), MUSEOS_ADMIN_PASS, DASHLY_RO_PASSWORD,
           BAK_DIR (ruta DENTRO del servidor SQL donde están los .bak; por defecto /bak)
Opciones:  --solo-plan   muestra los RESTORE que haría, sin ejecutarlos
"""
import glob, os, re, sys, time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "bi"))
import pymssql
import cargar_decisiones as cd  # reutiliza conectar() y ejecutar_script()

BAK_DIR = os.getenv("BAK_DIR", "/bak")
DATA_DIR = os.getenv("SQL_DATA_DIR", "/var/opt/mssql/data")
BASES = [("MuseosLatam_Datamart", "MuseosLatam_Datamart_*.bak")]  # el dashboard solo necesita el datamart (Origen es opcional)


def esperar(timeout=180):
    t0 = time.time()
    while True:
        try:
            c = pymssql.connect(os.getenv("MUSEOS_DB_HOST", "127.0.0.1"), os.getenv("MUSEOS_ADMIN_USER", "sa"), os.environ["MUSEOS_ADMIN_PASS"],
                                "master", port=int(os.getenv("MUSEOS_DB_PORT", "14330")), timeout=0, login_timeout=5)
            c.autocommit(True)
            return c
        except pymssql.Error as e:
            if time.time() - t0 > timeout:
                sys.exit(f"SQL Server no responde tras {timeout}s: {e}")
            time.sleep(3)


def plan_restore(cur, base, patron):
    """Devuelve el T-SQL RESTORE para una base (archivo más reciente que cumple el patrón, nombres lógicos leídos del respaldo)."""
    cur.execute("SELECT 1 FROM sys.databases WHERE name=%s", (base,))
    if cur.fetchone():
        return None
    cands = sorted(glob.glob(os.path.join(BAK_DIR, patron))) if os.path.isdir(BAK_DIR) else []
    if not cands:
        raise SystemExit(f"No encuentro {patron} en {BAK_DIR}: monte los respaldos (solo lectura) en el mismo ruta en el servidor SQL y en este contenedor.")
    bak = cands[-1]
    cur.execute("RESTORE FILELISTONLY FROM DISK=%s", (bak,))
    files = cur.fetchall()
    mv = []
    for r in files:
        logico, tipo = r[0], r[2]
        mv.append(f"MOVE N'{logico}' TO N'{DATA_DIR}/{logico}.{'ldf' if tipo == 'L' else 'mdf'}'")
    return bak, f"RESTORE DATABASE [{base}] FROM DISK=N'{bak}' WITH CHECKSUM,RECOVERY," + ",".join(mv) + ",STATS=25"


def main():
    solo_plan = "--solo-plan" in sys.argv
    conn = esperar()
    cur = conn.cursor()
    cur.execute("SELECT CONVERT(int,SERVERPROPERTY('ProductMajorVersion'))")
    if cur.fetchone()[0] < 15:
        sys.exit("Se requiere SQL Server 2019 o posterior.")
    for base, patron in BASES:
        p = plan_restore(cur, base, patron)
        if p is None:
            print(f"- {base}: ya existe; no se restaura (nunca se sobrescribe).")
            continue
        bak, sql = p
        print(f"- {base}: restaurar desde {bak}")
        if solo_plan:
            print("   ", sql)
            continue
        cur.execute(f"RESTORE VERIFYONLY FROM DISK=N'{bak}' WITH CHECKSUM")
        cur.execute(sql)
        while cur.nextset():
            pass
        print(f"  {base} restaurada.")
    if solo_plan:
        return
    pw = os.environ.get("DASHLY_RO_PASSWORD")
    if not pw:
        sys.exit("Defina DASHLY_RO_PASSWORD (contraseña del usuario de solo lectura del dashboard).")
    cur.execute("SELECT 1 FROM sys.server_principals WHERE name='dashly_ro'")
    if not cur.fetchone():
        cur.execute("CREATE LOGIN dashly_ro WITH PASSWORD=%s,CHECK_POLICY=OFF", (pw,))
        print("- login dashly_ro creado.")
    else:
        print("- login dashly_ro ya existía (no se cambia su contraseña).")
    cur.execute("USE MuseosLatam_Datamart")
    cur.execute("IF DATABASE_PRINCIPAL_ID('dashly_ro') IS NULL CREATE USER dashly_ro FOR LOGIN dashly_ro ELSE ALTER USER dashly_ro WITH LOGIN=dashly_ro")  # el respaldo trae el usuario huérfano
    print("- construyendo la capa BI …", flush=True)
    # El backup entregado ya está depurado. Nunca borrar columnas de otra copia
    # simplemente por inicializar el dashboard; conservar idioma/confianza si existen.
    if '--aplicar-depuracion-historica' in sys.argv:
        sys.exit('La depuración histórica elimina evidencia. Respaldar y revisar sus SQL manualmente; no se aplica desde init_db.py.')
    for s in ("00_decisiones_setup.sql", "01_bi_setup.sql"):
        cd.ejecutar_script(conn, RAIZ / "bi" / s)
    cur.execute("SELECT COUNT(*) FROM bi.lugar_decision")
    csv_dec = RAIZ / "bi" / "decisiones_vigentes.csv"
    if cur.fetchone()[0] == 0 and csv_dec.exists():
        print("- aplicando la curaduría vigente (bi/decisiones_vigentes.csv) …", flush=True)
        import subprocess
        r = subprocess.run([sys.executable, str(RAIZ / "bi" / "cargar_decisiones.py"), str(csv_dec), "--aplicar", "--reconstruir"], env=os.environ)
        if r.returncode != 0:
            sys.exit(f"La carga de decisiones falló (código {r.returncode}).")
    cur.execute("SELECT ok,resenas_datamart,resenas_bi FROM bi.v_control_reconciliacion")
    ok, a, b = cur.fetchone()
    print(f"- reconciliación: datamart {a:,} / BI {b:,} -> {'OK' if ok == 1 else 'NO CUADRA'}")
    sys.exit(0 if ok == 1 else 1)


if __name__ == "__main__":
    main()
