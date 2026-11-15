"""login_google.py — Abre Chrome (con ventana) sobre un perfil dedicado para iniciar sesion en Google UNA vez.

Maps (oct-2026) limita a 5 reseñas por lugar a sesiones anonimas ("Accede para ... leer todas las
opiniones"). Tras iniciar sesion aqui, usar:  scrape_museos_v2.py --pais argentina --perfil <dir>
Usar una cuenta de Google dedicada, no personal. Cierra la ventana al terminar (no requiere teclado).
"""
import sys
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

dir_ = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "logs" / "chrome_perfil_google")
dir_.mkdir(parents=True, exist_ok=True)
o = Options()
o.add_argument(f"--user-data-dir={dir_}"); o.add_argument("--window-size=1200,900"); o.add_argument("--lang=es")
d = webdriver.Chrome(options=o)
d.get("https://accounts.google.com/ServiceLogin?service=chromiumsync&continue=https://www.google.com/maps")
print(f"Inicia sesion en la ventana de Chrome (perfil: {dir_}). CIERRA la ventana al terminar.", flush=True)
import time
while True:  # no requiere teclado: termina cuando cierras la ventana
    try:
        if not d.window_handles:
            break
    except Exception:
        break
    time.sleep(2)
print("Ventana cerrada: sesion guardada en el perfil.")
