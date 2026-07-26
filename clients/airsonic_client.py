"""Cliente Subsonic API para Airsonic — lista artistas y álbumes de la biblioteca."""
import hashlib
import secrets

import requests


class AirsonicError(Exception):
    pass


def _params(user, password, version, use_token=True, **extra):
    base = {"u": user, "v": version, "c": "discografia-gaps", "f": "json"}
    if use_token:
        salt = secrets.token_hex(8)
        token = hashlib.md5((password + salt).encode()).hexdigest()
        base.update({"t": token, "s": salt})
    else:
        # Algunos Airsonic (p.ej. cuentas que no soportan auth por hash) piden
        # explicitamente password en claro via el mensaje de error de abajo.
        base["p"] = password
    return {**base, **extra}


def _raw_call(base_url, user, password, version, endpoint, use_token=True, **kwargs):
    url = f"{base_url}/rest/{endpoint}.view"
    resp = requests.get(url, params=_params(user, password, version, use_token, **kwargs), timeout=15)
    resp.raise_for_status()
    return resp.json().get("subsonic-response", {})


def _call(base_url, user, password, version, endpoint, **kwargs):
    """Llama al endpoint con `version`, con dos reintentos automaticos:

    - Error 30 ("Server must upgrade"): la version pedida es mas nueva de lo
      que el servidor soporta -- reintenta con la version que el propio
      servidor reporta en su respuesta.
    - "...try authenticating via non-hashed password": el servidor no acepta
      auth por token (hash+salt) para esta cuenta -- reintenta con la
      contrasena en claro (parametro `p`) en vez de `t`/`s`.

    Asi el usuario no tiene que adivinar ni AIRSONIC_API_VERSION ni el modo
    de auth a mano."""
    use_token = True
    data = _raw_call(base_url, user, password, version, endpoint, use_token, **kwargs)

    if data.get("status") != "ok":
        err = data.get("error", {})

        if err.get("code") == 30:
            server_version = data.get("version")
            if server_version and server_version != version:
                print(f"  [airsonic] version {version} rechazada, reintentando con {server_version} "
                      f"(guarda AIRSONIC_API_VERSION={server_version} para saltarte este reintento)")
                version = server_version
                data = _raw_call(base_url, user, password, version, endpoint, use_token, **kwargs)
                err = data.get("error", {}) if data.get("status") != "ok" else {}

        if data.get("status") != "ok" and "non-hashed" in (err.get("message") or "").lower():
            print("  [airsonic] el servidor no acepta auth por token, reintentando con password en claro")
            use_token = False
            data = _raw_call(base_url, user, password, version, endpoint, use_token, **kwargs)

        if data.get("status") != "ok":
            err = data.get("error", {})
            raise AirsonicError(err.get("message", "Unknown Airsonic error"))

    return data


def list_artists(base_url, user, password, version="1.15.0"):
    """Devuelve [{name, id, albumCount}, ...] recorriendo getArtists.view."""
    data = _call(base_url, user, password, version, "getArtists")
    indexes = data.get("artists", {}).get("index", [])
    artists = []
    for index in indexes:
        for artist in index.get("artist", []):
            artists.append({
                "name": artist.get("name"),
                "id": artist.get("id"),
                "albumCount": artist.get("albumCount", 0),
            })
    return artists


def list_albums(base_url, user, password, version, artist_id):
    """Devuelve [{name, id, year}, ...] de un artista concreto via getArtist.view
    (el mismo endpoint que en el navegador muestra la pagina de un artista,
    incluye 'album' anidado con nombre/anio/id de cada disco de la biblioteca)."""
    data = _call(base_url, user, password, version, "getArtist", id=artist_id)
    albums = data.get("artist", {}).get("album", [])
    return [
        {"name": a.get("name"), "id": a.get("id"), "year": a.get("year")}
        for a in albums
    ]
