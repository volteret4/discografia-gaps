"""Normaliza nombres de artista para poder cruzarlos entre fuentes distintas
(mayusculas/acentos/'The '/puntuacion difieren entre Muspy, Airsonic,
qBittorrent y Last.fm aunque sea el mismo artista)."""
import re
import unicodedata

_LEADING_THE = re.compile(r"^the\s+")
_NON_WORD = re.compile(r"[^\w]")


def normalize(name):
    if not name:
        return ""
    s = name.strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = _LEADING_THE.sub("", s)
    s = _NON_WORD.sub("", s)
    return s
