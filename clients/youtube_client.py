"""Busca un video de YouTube para un disco (artista+album) -- scraping de la
pagina de resultados, sin API key. Adaptado de
mixxx_info/src/links.py::_youtube (misma tecnica, cambia la query de
"artista + titulo de pista" a "artista + titulo de album")."""
import re

import requests

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; discografia-gaps/0.1)"}


def search_album(artist, album):
    """Devuelve la URL del primer resultado, o None si no se encuentra nada."""
    query = f"{artist} {album} full album".replace(" ", "+")
    try:
        resp = requests.get(
            f"https://www.youtube.com/results?search_query={query}",
            headers=_HEADERS,
            timeout=12,
        )
        ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp.text)
        return f"https://www.youtube.com/watch?v={ids[0]}" if ids else None
    except Exception:
        return None
