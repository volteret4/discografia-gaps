#!/usr/bin/env python3
"""
Flask app — para cada artista de tu universo (Muspy ∪ Airsonic ∪ Last.fm),
muestra que discos (Album/EP, via MusicBrainz) te faltan en la biblioteca, y
permite comprobar bajo demanda si esos discos que faltan estan disponibles
en Orpheus (descarga, con confirmacion explicita antes de tocar
qBittorrent), YouTube o Bandcamp.
"""
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, render_template, request

from clients import bandcamp_client, orpheus_client, qbittorrent_client, youtube_client
from config import DB_PATH, ORPHEUS_APIKEY, QB_DOWNLOAD_CATEGORY, QB_HOST, QB_PASS, QB_PORT, QB_USER
from scan import init_db

app = Flask(__name__)

AVAILABILITY_CACHE_DAYS = 7

# ── Panel de configuracion (⚙) — mismo patron que artist-sync/trasvase ─────
SETTINGS_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
SETTINGS_PASSWORD = os.environ.get("SETTINGS_PASSWORD", "")
# "live": True = solo lo usa scan.py (subproceso nuevo en cada sync, relee
# config.py) -- efecto inmediato con solo guardar. Sin ese flag, la variable
# tambien la usa este mismo proceso Flask de larga duracion (fijada una vez
# al arrancar, ver imports de arriba) -- ahi si hace falta recrear el
# contenedor.
VARS_SPEC = [
    {"name": "MUSPY_USERNAME", "secret": False, "live": True, "help": "Usuario de Muspy"},
    {"name": "MUSPY_PASSWORD", "secret": True, "live": True, "help": "Contraseña de Muspy"},
    {"name": "AIRSONIC_URL", "secret": False, "live": True, "help": "URL base de Airsonic"},
    {"name": "AIRSONIC_USER", "secret": False, "live": True, "help": "Usuario Airsonic"},
    {"name": "AIRSONIC_PASSWORD", "secret": True, "live": True, "help": "Contraseña Airsonic"},
    {"name": "AIRSONIC_API_VERSION", "secret": False, "live": True,
     "help": "Versión de API Subsonic a declarar (ej. 1.15.0)"},
    {"name": "LASTFM_API_KEY", "secret": True, "live": True,
     "help": "API key de Last.fm — solo hace falta si NO hay espejo compartido (lastfm_data) montado"},
    {"name": "LASTFM_USERNAME", "secret": False, "live": True, "help": "Usuario de Last.fm"},
    {"name": "LASTFM_MIN_PLAYCOUNT", "secret": False, "live": True, "default": "0",
     "help": "Umbral de scrobbles para AÑADIR artistas al universo desde Last.fm — 0 desactiva este filtro"},
    {"name": "MB_EMAIL", "secret": False, "live": True,
     "help": "Email de contacto para la API de MusicBrainz (lo piden en el User-Agent)"},
    {"name": "QB_HOST", "secret": False, "help": "Host/IP de qBittorrent"},
    {"name": "QB_PORT", "secret": False, "default": "8080", "help": "Puerto WebUI de qBittorrent"},
    {"name": "QB_USER", "secret": False, "help": "Usuario WebUI de qBittorrent"},
    {"name": "QB_PASS", "secret": True, "help": "Contraseña WebUI de qBittorrent"},
    {"name": "QB_CATEGORY", "secret": False, "help": "Categoria de qBittorrent a escanear para 'have' (vacio = todas)"},
    {"name": "QB_DOWNLOAD_CATEGORY", "secret": False,
     "help": "Categoria con la que se añaden en qBittorrent los torrents descargados desde aqui (vacio = sin categoria)"},
    {"name": "QB_REMOTE_PATH", "secret": False, "live": True,
     "help": "Solo si qBittorrent corre en SU PROPIO contenedor: ruta tal cual la reporta su API"},
    {"name": "DISCOGRAFIA_GAPS_QB_MUSIC_PATH", "secret": False, "location": "root",
     "help": "Ruta host donde qBittorrent guarda las descargas (bind mount — requiere recrear el contenedor)"},
    {"name": "ORPHEUS_APIKEY", "secret": True, "help": "API key de Orpheus.network"},
]
_HAS_SECRETS = any(v.get("secret") for v in VARS_SPEC)


def _settings_path(spec):
    if spec.get("location") == "root":
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "root.env")
    return SETTINGS_ENV_PATH


def _current_value(spec):
    from plain_env import read_env_file
    file_vals = read_env_file(_settings_path(spec))
    if spec["name"] in file_vals:
        return file_vals[spec["name"]]
    return os.environ.get(spec["name"], spec.get("default", ""))


def _check_auth(password):
    if not SETTINGS_PASSWORD:
        return not _HAS_SECRETS
    return password == SETTINGS_PASSWORD


@app.route("/api/settings", methods=["POST"])
def api_settings():
    d = request.get_json(silent=True) or {}
    password = d.get("password") or ""
    requires = bool(SETTINGS_PASSWORD) or _HAS_SECRETS
    authorized = _check_auth(password)
    if requires and not authorized:
        error = "Contraseña incorrecta" if password else None
        if not SETTINGS_PASSWORD:
            error = "Este servicio tiene credenciales pero no hay SETTINGS_PASSWORD configurada. Añádela al .env y reinicia el contenedor."
        return jsonify({"requires_password": True, "authorized": False, "error": error})
    vars_out = [
        {"name": v["name"], "value": _current_value(v), "secret": v["secret"], "help": v.get("help", "")}
        for v in VARS_SPEC
    ]
    return jsonify({"requires_password": requires, "authorized": True, "vars": vars_out})


@app.route("/api/settings/save", methods=["POST"])
def api_settings_save():
    from plain_env import write_env_file
    d = request.get_json(silent=True) or {}
    if not _check_auth(d.get("password") or ""):
        return jsonify({"error": "Contraseña incorrecta"}), 403
    by_name = {v["name"]: v for v in VARS_SPEC}
    updates = {k: v for k, v in (d.get("values") or {}).items() if k in by_name}
    if not updates:
        return jsonify({"error": "Nada que guardar"}), 400
    by_path = {}
    for k, v in updates.items():
        path = _settings_path(by_name[k])
        by_path.setdefault(path, {})[k] = v
    for path, vals in by_path.items():
        write_env_file(path, vals)
    touched_root = any(_settings_path(by_name[k]).endswith("root.env") for k in updates)
    needs_restart = any(not by_name[k].get("live") for k in updates)
    if touched_root:
        message = ("Guardado. DISCOGRAFIA_GAPS_QB_MUSIC_PATH es una ruta de bind mount — hace falta "
                    "RECREAR el contenedor (docker compose up -d --build), no basta con reiniciarlo.")
    elif needs_restart:
        message = "Guardado. Reinicia el contenedor para aplicar los cambios."
    else:
        message = "Guardado. Ya tiene efecto en la próxima sincronización (botón \"Sincronizar\"), sin tocar el contenedor."
    return jsonify({"ok": True, "message": message})


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


with get_db() as _conn:
    init_db(_conn)


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# API — sync
# ---------------------------------------------------------------------------

@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Relanza scan.py (todas las fases o una lista via ?only=universe,discography,have)."""
    only = request.args.get("only")
    force = request.args.get("force_discography") == "1"
    scan_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan.py")
    cmd = ["python3", scan_script]
    if only:
        cmd += ["--only", only]
    if force:
        cmd += ["--force-discography"]
    try:
        # La primera sincronizacion completa (universo + discografia de TODOS
        # los artistas, un request a MusicBrainz por artista con ~1s de
        # cortesia entre llamadas) puede tardar bastante mas que el timeout
        # de artist-sync -- 30 minutos de margen.
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return jsonify({"error": "La sincronizacion tardo demasiado (timeout)"}), 500
    return jsonify({
        "success": res.returncode == 0,
        "log": (res.stdout + "\n" + res.stderr)[-4000:],
    })


@app.route("/api/last-sync")
def api_last_sync():
    conn = get_db()
    has_data = conn.execute("SELECT 1 FROM artists LIMIT 1").fetchone() is not None
    conn.close()
    if not has_data or not os.path.exists(DB_PATH):
        return jsonify({"last_sync": None})
    return jsonify({"last_sync": os.path.getmtime(DB_PATH)})


# ---------------------------------------------------------------------------
# API — artistas / discografia
# ---------------------------------------------------------------------------

@app.route("/api/artists")
def api_artists():
    conn = get_db()
    rows = conn.execute(
        """SELECT a.id, a.name,
                  COUNT(rg.id) AS total_count,
                  SUM(CASE WHEN rg.have = 0 THEN 1 ELSE 0 END) AS missing_count,
                  GROUP_CONCAT(DISTINCT s.source) AS sources
           FROM artists a
           LEFT JOIN release_groups rg ON rg.artist_id = a.id
           LEFT JOIN artist_sources s ON s.artist_id = a.id
           GROUP BY a.id
           ORDER BY a.name COLLATE NOCASE"""
    ).fetchall()
    conn.close()
    return jsonify([
        {
            "id": r["id"],
            "name": r["name"],
            "total_count": r["total_count"] or 0,
            "missing_count": r["missing_count"] or 0,
            "sources": (r["sources"] or "").split(",") if r["sources"] else [],
        }
        for r in rows
    ])


@app.route("/api/artists/<int:artist_id>/albums")
def api_artist_albums(artist_id):
    conn = get_db()
    artist = conn.execute("SELECT id, name FROM artists WHERE id=?", (artist_id,)).fetchone()
    if not artist:
        conn.close()
        return jsonify({"error": "Artista no encontrado"}), 404
    albums = conn.execute(
        """SELECT id, title, primary_type, first_release_date, have, have_sources
           FROM release_groups WHERE artist_id=?
           ORDER BY first_release_date IS NULL, first_release_date""",
        (artist_id,),
    ).fetchall()
    conn.close()
    return jsonify({
        "artist": {"id": artist["id"], "name": artist["name"]},
        "albums": [
            {
                "id": a["id"],
                "title": a["title"],
                "primary_type": a["primary_type"],
                "first_release_date": a["first_release_date"],
                "have": bool(a["have"]),
                "have_sources": (a["have_sources"] or "").split(",") if a["have_sources"] else [],
            }
            for a in albums
        ],
    })


# ---------------------------------------------------------------------------
# API — disponibilidad (bajo demanda) y descarga
# ---------------------------------------------------------------------------

def _cached_availability(conn, release_group_id):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=AVAILABILITY_CACHE_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT source, url, meta, checked_at FROM availability WHERE release_group_id=? AND checked_at >= ?",
        (release_group_id, cutoff),
    ).fetchall()
    return {r["source"]: r for r in rows}


def _store_availability(conn, release_group_id, source, url, meta):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO availability(release_group_id, source, url, meta, checked_at) VALUES(?, ?, ?, ?, ?)""",
        (release_group_id, source, url, json.dumps(meta) if meta is not None else None, now),
    )


@app.route("/api/availability/<int:release_group_id>", methods=["POST"])
def api_availability(release_group_id):
    """Bajo demanda: comprueba Orpheus/YouTube/Bandcamp para ESTE disco y
    cachea el resultado (AVAILABILITY_CACHE_DAYS) para no repetir scraping /
    gastar rate-limit de Orpheus en cada re-visita a la pagina."""
    conn = get_db()
    row = conn.execute(
        """SELECT rg.title, a.name AS artist_name
           FROM release_groups rg JOIN artists a ON a.id = rg.artist_id
           WHERE rg.id=?""",
        (release_group_id,),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Disco no encontrado"}), 404

    cached = _cached_availability(conn, release_group_id)
    result = {}

    if "orpheus" in cached:
        r = cached["orpheus"]
        result["orpheus"] = {"url": r["url"], "torrents": json.loads(r["meta"]) if r["meta"] else []}
    elif ORPHEUS_APIKEY:
        try:
            groups = orpheus_client.search_album(ORPHEUS_APIKEY, row["artist_name"], row["title"])
            torrents = [t for g in groups for t in g["torrents"]]
            url = f"https://orpheus.network/torrents.php?id={groups[0]['group_id']}" if groups else None
            _store_availability(conn, release_group_id, "orpheus", url, torrents)
            result["orpheus"] = {"url": url, "torrents": torrents}
        except Exception as exc:
            result["orpheus"] = {"error": str(exc)}
    else:
        result["orpheus"] = {"error": "ORPHEUS_APIKEY no configurada"}

    if "youtube" in cached:
        result["youtube"] = {"url": cached["youtube"]["url"]}
    else:
        url = youtube_client.search_album(row["artist_name"], row["title"])
        _store_availability(conn, release_group_id, "youtube", url, None)
        result["youtube"] = {"url": url}

    if "bandcamp" in cached:
        result["bandcamp"] = {"url": cached["bandcamp"]["url"]}
    else:
        url = bandcamp_client.search_album(row["artist_name"], row["title"])
        _store_availability(conn, release_group_id, "bandcamp", url, None)
        result["bandcamp"] = {"url": url}

    conn.commit()
    conn.close()
    return jsonify(result)


@app.route("/api/orpheus/download", methods=["POST"])
def api_orpheus_download():
    """La UNICA accion que toca qBittorrent -- solo se llama tras el clic
    explicito de "Descargar" sobre un torrent concreto ya mostrado en la UI."""
    if not ORPHEUS_APIKEY:
        return jsonify({"error": "ORPHEUS_APIKEY no configurada"}), 400
    if not QB_PASS:
        return jsonify({"error": "qBittorrent no configurado"}), 400
    d = request.get_json(silent=True) or {}
    torrent_id = d.get("torrent_id")
    if not torrent_id:
        return jsonify({"error": "Falta torrent_id"}), 400

    try:
        _, authkey, passkey = orpheus_client.auth_keys(ORPHEUS_APIKEY)
        url = orpheus_client.download_url(torrent_id, authkey, passkey)
        qbittorrent_client.add_torrent(QB_HOST, QB_PORT, QB_USER, QB_PASS, url, category=QB_DOWNLOAD_CATEGORY)
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


if __name__ == "__main__":
    from config import FLASK_HOST, FLASK_PORT
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True)
