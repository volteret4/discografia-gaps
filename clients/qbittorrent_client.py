"""Cliente qBittorrent WebUI API — lista rutas de contenido y añade torrents nuevos."""
import os

import requests


class QbittorrentError(Exception):
    pass


def _base_url(host, port):
    return f"http://{host}:{port}"


def _session(host, port, user, password):
    s = requests.Session()
    base = _base_url(host, port)
    resp = s.post(f"{base}/api/v2/auth/login", data={"username": user, "password": password}, timeout=10)
    if resp.status_code != 200 or resp.text.strip() != "Ok.":
        raise QbittorrentError(f"Login fallido en qBittorrent: {resp.status_code} {resp.text}")
    return s


def list_content_paths(host, port, user, password, category="", remote_path="", local_path=""):
    """Devuelve la lista de rutas (carpeta o archivo) de cada torrent.

    Si qBittorrent corre en su propio contenedor, las rutas que reporta su
    API (content_path/save_path) son las que VE ESE contenedor (p.ej.
    "/downloads/Album X"), no necesariamente las que ve el filesystem donde
    corre esta app. `remote_path`/`local_path` reescriben ese prefijo por la
    ruta real donde esta app tiene montada la misma carpeta. Si `remote_path`
    esta vacio, no se reescribe nada (asume mismo filesystem)."""
    s = _session(host, port, user, password)
    base = _base_url(host, port)
    params = {"category": category} if category else {}
    resp = s.get(f"{base}/api/v2/torrents/info", params=params, timeout=20)
    resp.raise_for_status()
    torrents = resp.json()

    paths = []
    for t in torrents:
        content_path = t.get("content_path")
        if not content_path:
            content_path = os.path.join(t.get("save_path", ""), t.get("name", ""))
        if remote_path and content_path.startswith(remote_path):
            content_path = local_path + content_path[len(remote_path):]
        paths.append(content_path)
    return paths


def add_torrent(host, port, user, password, url, category=""):
    """Añade un torrent nuevo a qBittorrent a partir de una URL de descarga
    (p.ej. la que construye orpheus_client.download_url) o un magnet link.

    Es la UNICA funcion de este servicio que efectivamente dispara una
    descarga real -- se llama solo desde /api/orpheus/download, tras el
    clic explicito de "Descargar" en la UI, nunca automaticamente."""
    s = _session(host, port, user, password)
    base = _base_url(host, port)
    data = {"urls": url}
    if category:
        data["category"] = category
    resp = s.post(f"{base}/api/v2/torrents/add", data=data, timeout=20)
    if resp.status_code != 200:
        raise QbittorrentError(f"No se pudo anadir el torrent: {resp.status_code} {resp.text}")
    return True
