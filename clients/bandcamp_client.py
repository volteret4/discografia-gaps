"""Busca un disco en Bandcamp -- scraping de la pagina de resultados, sin API
key. Adaptado de mixxx_info/src/links.py::_bandcamp (misma tecnica, busca
por album/track en vez de solo track)."""
import requests
from bs4 import BeautifulSoup

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; discografia-gaps/0.1)"}


def search_album(artist, album):
    """Devuelve la URL del primer resultado de tipo album, o None."""
    query = f"{artist} {album}".replace(" ", "+")
    try:
        resp = requests.get(
            f"https://bandcamp.com/search?q={query}&item_type=a",
            headers=_HEADERS,
            timeout=12,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        link = soup.select_one(".result-info .heading a")
        return link["href"].split("?")[0] if link else None
    except Exception:
        return None
