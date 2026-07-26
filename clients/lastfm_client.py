"""Cliente Last.fm — top artistas escuchados (user.getTopArtists, period=overall)."""
import requests

API_URL = "https://ws.audioscrobbler.com/2.0/"
PAGE_SIZE = 200


class LastfmError(Exception):
    pass


def top_artists(api_key, username, period="overall", min_playcount=0):
    """Devuelve [{name, playcount, mbid}, ...] con playcount >= min_playcount."""
    artists = []
    page = 1
    while True:
        params = {
            "method": "user.gettopartists",
            "user": username,
            "api_key": api_key,
            "format": "json",
            "period": period,
            "limit": PAGE_SIZE,
            "page": page,
        }
        resp = requests.get(API_URL, params=params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        if "error" in payload:
            raise LastfmError(payload.get("message", "Unknown Last.fm error"))

        top = payload.get("topartists", {})
        chunk = top.get("artist", [])
        if not chunk:
            break

        stop = False
        for a in chunk:
            playcount = int(a.get("playcount", 0))
            if playcount < min_playcount:
                stop = True
                break
            artists.append({
                "name": a.get("name"),
                "playcount": playcount,
                "mbid": a.get("mbid") or None,
            })

        attr = top.get("@attr", {})
        total_pages = int(attr.get("totalPages", page))
        if stop or page >= total_pages:
            break
        page += 1

    return artists
