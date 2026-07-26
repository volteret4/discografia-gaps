"""Extrae artista/album de archivos FLAC bajo una serie de rutas raiz (una
por torrent de qBittorrent), para saber que discos concretos hay descargados
(no solo que artistas)."""
import os
from collections import Counter

from mutagen import MutagenError
from mutagen.flac import FLAC


def _tag(audio, *keys):
    for key in keys:
        for variant in (key.upper(), key.lower(), key.title()):
            val = audio.get(variant)
            if val:
                return str(val[0]).strip()
    return None


def _read_artist_album(flac_path):
    try:
        audio = FLAC(flac_path)
    except (MutagenError, OSError):
        return None, None
    artist = _tag(audio, "albumartist", "artist")
    album = _tag(audio, "album")
    return artist, album


def _read_artist(flac_path):
    artist, _album = _read_artist_album(flac_path)
    return artist


def _first_flac_per_dir(root_paths):
    """Recorre root_paths y devuelve un (artist, album) por carpeta que
    contenga FLACs (leidos de un solo archivo, igual criterio que
    scan_artist_track_counts: son pistas del mismo disco)."""
    for root in root_paths:
        if not root:
            continue
        if os.path.isfile(root):
            if root.lower().endswith(".flac"):
                yield _read_artist_album(root)
            continue
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            flac_files = [f for f in files if f.lower().endswith(".flac")]
            if not flac_files:
                continue
            yield _read_artist_album(os.path.join(dirpath, flac_files[0]))


def scan_artist_track_counts(root_paths):
    """root_paths: iterable de rutas (carpeta de contenido de cada torrent).
    Devuelve {artist_name: track_count}."""
    counts = Counter()

    for root in root_paths:
        if not root:
            continue
        if os.path.isfile(root):
            if root.lower().endswith(".flac"):
                artist = _read_artist(root)
                if artist:
                    counts[artist] += 1
            continue
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            flac_files = [f for f in files if f.lower().endswith(".flac")]
            if not flac_files:
                continue
            artist = _read_artist(os.path.join(dirpath, flac_files[0]))
            if not artist:
                continue
            counts[artist] += len(flac_files)

    return dict(counts)


def scan_artist_albums(root_paths):
    """root_paths: iterable de rutas (carpeta de contenido de cada torrent).
    Devuelve una lista de {artist, album} (sin duplicados) -- una entrada por
    carpeta con FLACs, usada para marcar `have` a nivel de disco concreto
    (no solo de artista) en release_groups."""
    seen = set()
    out = []
    for artist, album in _first_flac_per_dir(root_paths):
        if not artist or not album:
            continue
        key = (artist, album)
        if key in seen:
            continue
        seen.add(key)
        out.append({"artist": artist, "album": album})
    return out
