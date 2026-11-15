"""check_sesion.py — exit 0 si el perfil de Chrome tiene sesion de Google valida en Maps; 1 si no; 2 si no se pudo evaluar."""
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "repos" / "googlemaps-reviews-scraper-es"))
from googlemaps import GoogleMapsScraper
from selenium.webdriver.common.by import By
perfil = sys.argv[1]; url = sys.argv[2]
try:
    sc = GoogleMapsScraper(debug=False, turbo=True, user_data_dir=perfil)
    d = sc.driver; d.set_window_size(1366, 1400); d.get(url); time.sleep(7)
    body = d.find_element(By.TAG_NAME, "body").text
    tabs = [t.text for t in d.find_elements(By.XPATH, '//button[@role="tab"]')]
    sc.__exit__(None, None, None)
    anonimo = ("Acceder" in body[:3000]) or ("vista limitada" in body)
    print("anonimo" if anonimo else "con_sesion", tabs)
    sys.exit(1 if anonimo else 0)
except Exception as e:
    print("error", e); sys.exit(2)
