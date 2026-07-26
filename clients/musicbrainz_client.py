"""Resuelve el MBID de un artista por nombre, y trae su discografia completa
(release-groups: Album/EP) desde MusicBrainz."""
import time

import requests

SEARCH_URL = "https://musicbrainz.org/ws/2/artist/"
RELEASE_GROUP_URL = "https://musicbrainz.org/ws/2/release-group"
PAGE_SIZE = 100

# Secondary-types que NO cuentan como "disco que me falta" en un uso
# habitual de completismo -- directos/recopilatorios/remixes/BSOs no son el
# mismo tipo de lanzamiento que un album o EP de estudio "nuevo".
_EXCLUDED_SECONDARY_TYPES = {
    "Live", "Compilation", "Remix", "DJ-mix", "Mixtape/Street",
    "Soundtrack", "Interview", "Audiobook", "Spokenword", "Demo",
}


def _headers(contact_email):
    return {"User-Agent": f"discografia-gaps/1.0 ({contact_email})"}


def search_mbid(artist_name, contact_email="admin@localhost"):
    params = {"query": f"artist:{artist_name}", "fmt": "json", "limit": 1}
    resp = requests.get(SEARCH_URL, params=params, headers=_headers(contact_email), timeout=10)
    resp.raise_for_status()
    artists = resp.json().get("artists", [])
    if not artists:
        return None
    return artists[0].get("id")


def discography(artist_mbid, contact_email="admin@localhost", types=("album", "ep")):
    """Devuelve [{mbid, title, primary_type, first_release_date}, ...] para
    un artista, paginando y filtrando los secondary-types de
    _EXCLUDED_SECONDARY_TYPES (salvo que ese sea el UNICO tipo listado para
    el release-group, en cuyo caso no hay un primary-type "limpio" que
    prefereir y se deja pasar)."""
    headers = _headers(contact_email)
    type_param = "|".join(types)
    results = []
    offset = 0

    while True:
        params = {
            "artist": artist_mbid,
            "type": type_param,
            "fmt": "json",
            "limit": PAGE_SIZE,
            "offset": offset,
        }
        resp = requests.get(RELEASE_GROUP_URL, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for rg in data.get("release-groups", []):
            secondary = set(rg.get("secondary-types", []))
            if secondary and secondary.issubset(_EXCLUDED_SECONDARY_TYPES):
                continue
            results.append({
                "mbid": rg.get("id"),
                "title": rg.get("title"),
                "primary_type": rg.get("primary-type"),
                "first_release_date": rg.get("first-release-date") or None,
            })

        total = data.get("release-group-count", len(results))
        offset += PAGE_SIZE
        if offset >= total:
            break
        # Rate limit cortes de MusicBrainz (~1 req/s) solo hace falta entre
        # paginas del mismo artista -- el espaciado ENTRE artistas lo hace
        # scan.py.
        time.sleep(1)

    return results
