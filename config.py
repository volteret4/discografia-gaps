import os
from plain_env import read_env_file
from sops_env import load_sops_env

try:
    load_sops_env()
except FileNotFoundError:
    # En Docker las variables llegan ya descifradas vía docker-compose (scripts/up.sh)
    print("Aviso: no se encontró .encrypted.env; usando variables de entorno ya exportadas")

# Sobrescribe con el .env plano que escribe el panel ⚙ (app.py) -- Docker solo
# inyecta env_file al CREAR el contenedor, así que sin esto un cambio guardado
# en el panel se queda sin efecto hasta recrear el contenedor. scan.py se
# relanza como subproceso nuevo en cada sync, así que esto basta para que
# recoja cambios de configuración sin rebuild ni restart.
os.environ.update(read_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "discografia_gaps.db")

FLASK_HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.environ.get("FLASK_PORT", 5000))

# Muspy — universo de artistas seguidos (mismas credenciales que artist-sync)
MUSPY_USERNAME = os.environ.get("MUSPY_USERNAME", "")
MUSPY_PASSWORD = os.environ.get("MUSPY_PASSWORD", "")

# Airsonic / Subsonic API — mismos nombres que artist-sync/dieta_sonora_stats
AIRSONIC_URL          = os.environ.get("AIRSONIC_URL", "http://localhost:4040")
AIRSONIC_USER         = os.environ.get("AIRSONIC_USER", "admin")
AIRSONIC_PASSWORD     = os.environ.get("AIRSONIC_PASSWORD", "")
AIRSONIC_API_VERSION  = os.environ.get("AIRSONIC_API_VERSION", "1.15.0")

# Last.fm — igual que artist-sync: espejo compartido (lastfm_data) primero,
# API directa como fallback. Aquí solo se usa para AÑADIR artistas al
# universo por encima de un umbral de scrobbles (filtro opcional del
# usuario), no para "have"/biblioteca.
LASTFM_SCROBBLES_DB = os.environ.get("LASTFM_SCROBBLES_DB", "/data/lastfm_stats.db")
LASTFM_API_KEY  = os.environ.get("LASTFM_API_KEY", "")
LASTFM_USERNAME = os.environ.get("LASTFM_USERNAME", "")
# Vacío/0 = no se añaden artistas por Last.fm, es un filtro opcional
LASTFM_MIN_PLAYCOUNT = int(os.environ.get("LASTFM_MIN_PLAYCOUNT", "0"))

# qBittorrent WebUI — mismos nombres que artist-sync (QB_HOST/PORT/USER/PASS)
QB_HOST = os.environ.get("QB_HOST", "localhost")
QB_PORT = os.environ.get("QB_PORT", "8080")
QB_USER = os.environ.get("QB_USER", "admin")
QB_PASS = os.environ.get("QB_PASS", "")
QB_CATEGORY = os.environ.get("QB_CATEGORY", "")
# Ruta FIJA dentro del contenedor donde esta app tiene montada la carpeta de
# descargas -- igual que en artist-sync, la ruta real del host se elige con
# DISCOGRAFIA_GAPS_QB_MUSIC_PATH en el .env raiz de tumtumpa.
QB_LOCAL_PATH = "/mnt/music/qbittorrent"
QB_REMOTE_PATH = os.environ.get("QB_REMOTE_PATH", "")
# Categoría en la que se añaden los torrents descargados desde este servicio
QB_DOWNLOAD_CATEGORY = os.environ.get("QB_DOWNLOAD_CATEGORY", "")

# MusicBrainz — discografía completa (release-groups) por artista
MB_EMAIL = os.environ.get("MB_EMAIL", "admin@localhost")

# Orpheus (Gazelle) — tracker privado usado para localizar descargas de los
# discos que faltan. Nombre de env var y formato de header estandarizados
# sobre el patrón de dieta_sonora/comparar_con_orpheus.py (no el de
# charts_orpheus, que usa un nombre y un prefijo de header distintos).
ORPHEUS_APIKEY = os.environ.get("ORPHEUS_APIKEY", "")

SETTINGS_PASSWORD = os.environ.get("SETTINGS_PASSWORD", "")
