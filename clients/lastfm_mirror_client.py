"""Lee artistas escuchados desde el espejo compartido de scrobbles de
tumtumpa (servicio lastfm-scrobbles: Last.fm + ListenBrainz ya
deduplicados en una sola tabla `scrobbles`, volumen Docker lastfm_data)
en vez de llamar a la API de Last.fm directamente. Evita repetir las
mismas consultas que ya hacen otros servicios del mismo tumtumpa, y de
paso incluye escuchas que solo vengan de ListenBrainz."""
import os
import sqlite3


def available(db_path):
    return bool(db_path) and os.path.exists(db_path)


def top_artists(db_path, min_playcount=0):
    """Devuelve [{name, playcount}, ...], agregando por artista todos los
    scrobbles del espejo (fuente Last.fm o ListenBrainz, ya deduplicados
    entre si por extraer_scrobbles.py)."""
    # immutable=1: el volumen se monta :ro, y sin esto sqlite3 igualmente
    # intenta crear un archivo de lock/journal en el mismo directorio incluso
    # para abrir en mode=ro -- falla con "unable to open database file" en
    # cuanto el directorio no admite escritura. immutable=1 le dice a SQLite
    # que confie en que el archivo no cambiara durante la conexion y se salte
    # todo eso.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    try:
        rows = conn.execute(
            """SELECT ar.name, COUNT(*) AS playcount
               FROM scrobbles s
               JOIN artists ar ON ar.artist_id = s.artist_id
               GROUP BY ar.artist_id
               HAVING playcount >= ?
               ORDER BY playcount DESC""",
            (min_playcount,),
        ).fetchall()
    finally:
        conn.close()
    return [{"name": name, "playcount": playcount} for name, playcount in rows]
