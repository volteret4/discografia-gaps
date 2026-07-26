#!/usr/bin/env python3
"""
Sincroniza el universo de artistas (Muspy ∪ Airsonic ∪ Last.fm por encima de
un umbral de scrobbles), trae la discografia (Album/EP) de cada uno desde
MusicBrainz, y marca que discos ya se tienen (Airsonic + qBittorrent/FLAC).

Uso:
    python scan.py                          # las 3 fases
    python scan.py --only universe
    python scan.py --only discography,have
    python scan.py --only discography --force-discography   # reescanea todo
"""
import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

from clients import airsonic_client, flac_scan, lastfm_client, lastfm_mirror_client, muspy_client, musicbrainz_client, qbittorrent_client
from clients.normalize import normalize
from config import (
    AIRSONIC_API_VERSION, AIRSONIC_PASSWORD, AIRSONIC_URL, AIRSONIC_USER,
    DB_PATH,
    LASTFM_API_KEY, LASTFM_MIN_PLAYCOUNT, LASTFM_SCROBBLES_DB, LASTFM_USERNAME,
    MB_EMAIL,
    MUSPY_PASSWORD, MUSPY_USERNAME,
    QB_CATEGORY, QB_HOST, QB_LOCAL_PATH, QB_PASS, QB_PORT, QB_REMOTE_PATH, QB_USER,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS artists (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    name                  TEXT NOT NULL,
    norm_name             TEXT NOT NULL UNIQUE,
    mbid                  TEXT,
    discography_synced_at TEXT
);

CREATE TABLE IF NOT EXISTS artist_sources (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    source    TEXT NOT NULL CHECK(source IN ('muspy', 'airsonic', 'lastfm')),
    UNIQUE(artist_id, source)
);

CREATE TABLE IF NOT EXISTS release_groups (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    artist_id           INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    mbid                TEXT UNIQUE,
    title               TEXT NOT NULL,
    norm_title          TEXT NOT NULL,
    primary_type        TEXT,
    first_release_date  TEXT,
    have                INTEGER NOT NULL DEFAULT 0,
    have_sources        TEXT
);
CREATE INDEX IF NOT EXISTS idx_rg_artist ON release_groups(artist_id);

CREATE TABLE IF NOT EXISTS availability (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    release_group_id INTEGER NOT NULL REFERENCES release_groups(id) ON DELETE CASCADE,
    source            TEXT NOT NULL CHECK(source IN ('orpheus', 'youtube', 'bandcamp')),
    url               TEXT,
    meta              TEXT,
    checked_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_avail_rg ON availability(release_group_id);
"""

# Re-sincroniza la discografia de un artista si la ultima sync tiene mas de
# esto -- evita repetir cientos de llamadas a MusicBrainz en cada
# "Sincronizar" una vez que ya esta poblado.
DISCOGRAPHY_REFRESH_DAYS = 30
MB_RATE_LIMIT_SECONDS = 1.0


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_artist(conn, name, mbid=None):
    norm = normalize(name)
    if not norm:
        return None
    conn.execute(
        """INSERT INTO artists(name, norm_name, mbid) VALUES(?, ?, ?)
           ON CONFLICT(norm_name) DO UPDATE SET mbid=COALESCE(mbid, excluded.mbid)""",
        (name, norm, mbid),
    )
    return conn.execute("SELECT id FROM artists WHERE norm_name=?", (norm,)).fetchone()[0]


def _artist_id_by_name(conn, name):
    row = conn.execute("SELECT id FROM artists WHERE norm_name=?", (normalize(name),)).fetchone()
    return row[0] if row else None


def replace_source_artists(conn, source, rows):
    """rows: [{name, mbid?}, ...]. Reemplaza por completo los artistas
    vinculados a esta fuente (borra el enlace en artist_sources + reinserta),
    igual filosofia que artist-sync/scan.py::replace_source -- si un artista
    desaparece de la fuente (deja de seguirse en Muspy, sale de la
    biblioteca...), su enlace con esa fuente desaparece tambien de aqui."""
    conn.execute("DELETE FROM artist_sources WHERE source=?", (source,))
    for row in rows:
        artist_id = upsert_artist(conn, row["name"], row.get("mbid"))
        if artist_id is None:
            continue
        conn.execute(
            "INSERT INTO artist_sources(artist_id, source) VALUES(?, ?) ON CONFLICT(artist_id, source) DO NOTHING",
            (artist_id, source),
        )
    conn.commit()
    print(f"  [{source}] {len(rows)} artistas")


def prune_orphan_artists(conn):
    """Artistas que se quedaron sin ninguna fuente (union vacia) -- el
    ON DELETE CASCADE se lleva por delante sus release_groups/availability."""
    cur = conn.execute("DELETE FROM artists WHERE id NOT IN (SELECT DISTINCT artist_id FROM artist_sources)")
    conn.commit()
    if cur.rowcount:
        print(f"  [universo] {cur.rowcount} artistas sin ninguna fuente, eliminados")


def sync_artist_universe(conn):
    if MUSPY_USERNAME and MUSPY_PASSWORD:
        try:
            user_id = muspy_client.get_user_id(MUSPY_USERNAME, MUSPY_PASSWORD)
            artists = muspy_client.list_followed_artists(MUSPY_USERNAME, MUSPY_PASSWORD, user_id)
            replace_source_artists(conn, "muspy", [{"name": a["name"], "mbid": a.get("mbid")} for a in artists])
        except Exception as exc:
            print(f"  [muspy] ERROR: {exc}", file=sys.stderr)
    else:
        print("  [muspy] sin credenciales, omitido")

    if AIRSONIC_PASSWORD:
        try:
            artists = airsonic_client.list_artists(AIRSONIC_URL, AIRSONIC_USER, AIRSONIC_PASSWORD, AIRSONIC_API_VERSION)
            replace_source_artists(conn, "airsonic", [{"name": a["name"]} for a in artists])
        except Exception as exc:
            print(f"  [airsonic] ERROR: {exc}", file=sys.stderr)
    else:
        print("  [airsonic] sin credenciales, omitido")

    if LASTFM_MIN_PLAYCOUNT > 0:
        try:
            if lastfm_mirror_client.available(LASTFM_SCROBBLES_DB):
                artists = lastfm_mirror_client.top_artists(LASTFM_SCROBBLES_DB, min_playcount=LASTFM_MIN_PLAYCOUNT)
            elif LASTFM_API_KEY and LASTFM_USERNAME:
                artists = lastfm_client.top_artists(LASTFM_API_KEY, LASTFM_USERNAME, min_playcount=LASTFM_MIN_PLAYCOUNT)
            else:
                print("  [lastfm] umbral de scrobbles activado pero sin espejo compartido ni credenciales de API, omitido")
                artists = None
            if artists is not None:
                replace_source_artists(conn, "lastfm", [{"name": a["name"], "mbid": a.get("mbid")} for a in artists])
        except Exception as exc:
            print(f"  [lastfm] ERROR: {exc}", file=sys.stderr)
    else:
        # Filtro desactivado (umbral 0) -- se limpia cualquier artista que
        # solo estuviera aqui por Last.fm de una configuracion anterior.
        replace_source_artists(conn, "lastfm", [])
        print("  [lastfm] filtro de scrobbles desactivado (LASTFM_MIN_PLAYCOUNT=0)")

    prune_orphan_artists(conn)


def sync_discography(conn, force=False):
    if force:
        rows = conn.execute("SELECT id, name, mbid FROM artists WHERE mbid IS NOT NULL").fetchall()
    else:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=DISCOGRAPHY_REFRESH_DAYS)).isoformat()
        rows = conn.execute(
            """SELECT id, name, mbid FROM artists WHERE mbid IS NOT NULL
               AND (discography_synced_at IS NULL OR discography_synced_at < ?)""",
            (cutoff,),
        ).fetchall()

    # Artistas sin MBID (tipicamente venidos solo de Airsonic/Last.fm) --
    # intenta resolverlo antes de descartarlos de la discografia.
    for artist_id, name in conn.execute("SELECT id, name FROM artists WHERE mbid IS NULL").fetchall():
        try:
            mbid = musicbrainz_client.search_mbid(name, MB_EMAIL)
        except Exception as exc:
            print(f"    ERROR resolviendo MBID de '{name}': {exc}", file=sys.stderr)
            mbid = None
        time.sleep(MB_RATE_LIMIT_SECONDS)
        if mbid:
            conn.execute("UPDATE artists SET mbid=? WHERE id=?", (mbid, artist_id))
            conn.commit()
            rows.append((artist_id, name, mbid))

    print(f"  [discografia] {len(rows)} artistas a sincronizar")
    for artist_id, name, mbid in rows:
        try:
            releases = musicbrainz_client.discography(mbid, MB_EMAIL)
        except Exception as exc:
            print(f"    ERROR discografia de '{name}': {exc}", file=sys.stderr)
            continue
        for r in releases:
            conn.execute(
                """INSERT INTO release_groups(artist_id, mbid, title, norm_title, primary_type, first_release_date)
                   VALUES(?, ?, ?, ?, ?, ?)
                   ON CONFLICT(mbid) DO UPDATE SET
                       title=excluded.title, norm_title=excluded.norm_title,
                       primary_type=excluded.primary_type, first_release_date=excluded.first_release_date""",
                (artist_id, r["mbid"], r["title"], normalize(r["title"]), r["primary_type"], r["first_release_date"]),
            )
        conn.execute(
            "UPDATE artists SET discography_synced_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), artist_id),
        )
        conn.commit()
        time.sleep(MB_RATE_LIMIT_SECONDS)


def _mark_have(conn, artist_id, norm_title, source):
    row = conn.execute(
        "SELECT id, have_sources FROM release_groups WHERE artist_id=? AND norm_title=?",
        (artist_id, norm_title),
    ).fetchone()
    if not row:
        return
    rg_id, have_sources = row
    sources = {s for s in (have_sources or "").split(",") if s}
    sources.add(source)
    conn.execute("UPDATE release_groups SET have=1, have_sources=? WHERE id=?", (",".join(sorted(sources)), rg_id))


def sync_have_status(conn):
    conn.execute("UPDATE release_groups SET have=0, have_sources=NULL")

    if AIRSONIC_PASSWORD:
        try:
            for a in airsonic_client.list_artists(AIRSONIC_URL, AIRSONIC_USER, AIRSONIC_PASSWORD, AIRSONIC_API_VERSION):
                artist_id = _artist_id_by_name(conn, a["name"])
                if not artist_id:
                    continue
                for album in airsonic_client.list_albums(AIRSONIC_URL, AIRSONIC_USER, AIRSONIC_PASSWORD, AIRSONIC_API_VERSION, a["id"]):
                    _mark_have(conn, artist_id, normalize(album["name"]), "airsonic")
            print("  [have/airsonic] hecho")
        except Exception as exc:
            print(f"  [have/airsonic] ERROR: {exc}", file=sys.stderr)
    else:
        print("  [have/airsonic] sin credenciales, omitido")

    if QB_PASS:
        try:
            paths = qbittorrent_client.list_content_paths(QB_HOST, QB_PORT, QB_USER, QB_PASS, QB_CATEGORY, QB_REMOTE_PATH, QB_LOCAL_PATH)
            for entry in flac_scan.scan_artist_albums(paths):
                artist_id = _artist_id_by_name(conn, entry["artist"])
                if not artist_id:
                    continue
                _mark_have(conn, artist_id, normalize(entry["album"]), "qbittorrent")
            print("  [have/qbittorrent] hecho")
        except Exception as exc:
            print(f"  [have/qbittorrent] ERROR: {exc}", file=sys.stderr)
    else:
        print("  [have/qbittorrent] sin credenciales, omitido")

    conn.commit()


PHASES = {
    "universe": sync_artist_universe,
    "discography": sync_discography,
    "have": sync_have_status,
}


def main():
    parser = argparse.ArgumentParser(description="Sincroniza universo de artistas + discografia + estado de biblioteca")
    parser.add_argument("--only", help="Lista separada por comas: universe,discography,have")
    parser.add_argument("--force-discography", action="store_true",
                         help="Reescanea la discografia de TODOS los artistas, no solo los pendientes/caducados")
    args = parser.parse_args()

    phases = list(PHASES)
    if args.only:
        phases = [p.strip() for p in args.only.split(",") if p.strip()]
        unknown = set(phases) - set(PHASES)
        if unknown:
            print(f"Fases desconocidas: {unknown}", file=sys.stderr)
            sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)

    for phase in phases:
        print(f"Sincronizando {phase}...")
        try:
            if phase == "discography":
                sync_discography(conn, force=args.force_discography)
            else:
                PHASES[phase](conn)
        except Exception as exc:
            print(f"  [{phase}] ERROR: {exc}", file=sys.stderr)

    conn.close()


if __name__ == "__main__":
    main()
