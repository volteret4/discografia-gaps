"""Cliente de la API Gazelle de Orpheus.network — busca un disco por
artista+titulo y construye la URL de descarga de un torrent concreto.

Patron calcado de dieta_sonora/buscar_nuevos.py y
dieta_sonora/comparar_con_orpheus.py: BASE_URL="https://orpheus.network/ajax.php",
header Authorization con la API key en crudo (sin prefijo "token "). Ese es
el patron que uso aqui de forma consistente -- charts_orpheus usa un nombre
de env var y un formato de header distintos, no lo replico."""
import time

import requests

BASE_URL = "https://orpheus.network/ajax.php"
DOWNLOAD_URL = "https://orpheus.network/torrents.php"
# Cortesia de rate-limit de Gazelle entre llamadas encadenadas (browse -> torrentgroup)
_REQUEST_DELAY = 1.5


class OrpheusError(Exception):
    pass


def _headers(api_key):
    return {"Authorization": api_key}


def _call(api_key, action, **params):
    resp = requests.get(BASE_URL, headers=_headers(api_key), params={"action": action, **params}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise OrpheusError(f"Orpheus action={action} fallo: {data}")
    return data["response"]


def auth_keys(api_key):
    """Devuelve (user_id, authkey, passkey) -- authkey/passkey hacen falta
    para construir la URL de descarga de un torrent (download_url)."""
    resp = _call(api_key, "index")
    return resp["id"], resp["authkey"], resp["passkey"]


def search_album(api_key, artist, album):
    """Busca `artist`+`album` en Orpheus. Devuelve
    [{group_id, torrents:[{id, format, media, encoding, size, remaster_year,
    remaster_title, file_count, seeders}, ...]}, ...]."""
    browse = _call(api_key, "browse", artistname=artist, groupname=album)
    groups = browse.get("results", []) or []

    out = []
    for g in groups:
        group_id = g.get("groupId")
        if group_id is None:
            continue
        time.sleep(_REQUEST_DELAY)
        tg = _call(api_key, "torrentgroup", id=group_id)
        torrents = [
            {
                "id": t.get("id"),
                "format": t.get("format"),
                "media": t.get("media"),
                "encoding": t.get("encoding"),
                "size": t.get("size"),
                "remaster_year": t.get("remasterYear"),
                "remaster_title": t.get("remasterTitle"),
                "file_count": t.get("fileCount"),
                "seeders": t.get("seeders"),
            }
            for t in tg.get("torrents", []) or []
        ]
        out.append({"group_id": group_id, "torrents": torrents})
    return out


def download_url(torrent_id, authkey, passkey):
    """Construye la URL de descarga de un torrent concreto -- no descarga
    los bytes, la URL se pasa tal cual a qbittorrent_client.add_torrent()."""
    return (
        f"{DOWNLOAD_URL}?action=download&id={torrent_id}"
        f"&authkey={authkey}&torrent_pass={passkey}&usetoken=1"
    )
