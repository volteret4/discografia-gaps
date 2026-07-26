# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Para cada artista de tu "universo" (Muspy seguidos ∪ Airsonic biblioteca ∪
Last.fm por encima de un umbral de scrobbles opcional), calcula su
discografía completa (Álbumes + EPs vía MusicBrainz release-groups) y marca
qué discos ya tienes (Airsonic + qBittorrent/FLAC) frente a los que te
faltan. Para un disco que falta, bajo demanda (no en el sync general),
comprueba si está disponible en Orpheus (tracker privado, descarga vía
qBittorrent con confirmación explícita), YouTube o Bandcamp.

## File Structure

- **`config.py`** — todas las credenciales/rutas, sobreescribibles por env var, carga `.encrypted.env` via `sops_env.py`
- **`clients/`** — un módulo por API externa: `muspy_client`, `airsonic_client`, `qbittorrent_client`, `lastfm_client`/`lastfm_mirror_client`, `musicbrainz_client`, `orpheus_client`, `youtube_client`, `bandcamp_client`; más `flac_scan.py` (tags FLAC) y `normalize.py` (clave de cruce de nombres de artista)
- **`scan.py`** — orquesta las 3 fases (`universe`, `discography`, `have`), upsert en `discografia_gaps.db`
- **`app.py`** — Flask: sirve la página + REST API + panel de ajustes (`⚙`, patrón compartido con `artist-sync`/`trasvase`)
- **`templates/index.html`** — página única (vanilla JS, sin build step): lista de artistas expandible a su discografía

## Database Schema (`discografia_gaps.db`, SQLite)

```sql
artists(id, name, norm_name UNIQUE, mbid, discography_synced_at)
artist_sources(id, artist_id FK, source IN (muspy|airsonic|lastfm))         -- de donde viene el interes
release_groups(id, artist_id FK, mbid UNIQUE, title, norm_title,
                primary_type, first_release_date, have, have_sources)        -- "disco" = release-group MB
availability(id, release_group_id FK, source IN (orpheus|youtube|bandcamp),
             url, meta, checked_at)                                          -- cache BAJO DEMANDA
```

`scan.py` reemplaza por completo `artist_sources` por fuente en cada sync
(igual filosofía que `presence` en `artist-sync`) y luego poda artistas sin
ninguna fuente (`prune_orphan_artists`) — el `ON DELETE CASCADE` se lleva
por delante su `release_groups`/`availability`.

## Key Logic Notes

- **`availability` es perezosa**: `scan.py` NUNCA llama a Orpheus/YouTube/
  Bandcamp — eso solo pasa desde `/api/availability/<id>` cuando el usuario
  expande un disco que falta en la web, y se cachea `AVAILABILITY_CACHE_DAYS`
  (7 días, en `app.py`) para no repetir scraping/rate-limit de Orpheus en
  cada visita.
- **Descargar es SIEMPRE explícito**: `/api/orpheus/download` es la única
  ruta que llama a `qbittorrent_client.add_torrent()` — solo se dispara tras
  el clic en "Descargar" de un torrent concreto ya mostrado (con confirm()
  en el frontend). Nunca se añade nada a qBittorrent automáticamente desde
  `scan.py` ni desde `/api/availability`.
- **Discografía = MusicBrainz release-groups, tipo Album/EP**:
  `clients/musicbrainz_client.py::discography()` excluye release-groups cuyo
  ÚNICO secondary-type sea Live/Compilation/Remix/DJ-mix/Soundtrack/etc.
  (`_EXCLUDED_SECONDARY_TYPES`) — si quieres que cuenten, hay que tocar esa
  constante.
- **Discogs NO está integrado (fase 2 deliberadamente fuera del MVP)**: cruzar
  dos listas de discografía con títulos "sucios" (MusicBrainz + Discogs) de
  forma fiable es trabajo real; MusicBrainz release-groups ya es fuente
  sólida por sí sola. El patrón a copiar cuando se añada está en
  `../bot_conciertos/handlers/artist_handlers.py::_get_discogs_artist_data()`.
- **`have` se marca por título exacto normalizado** (`normalize()`, mismo
  criterio que artist-sync para artistas: minúsculas, sin acentos/puntuación,
  sin "The " inicial) — un álbum "Deluxe Edition" en tu biblioteca que
  MusicBrainz titula distinto puede no cruzar. Limitación conocida del MVP,
  no hay fuzzy matching todavía.
- **`ORPHEUS_APIKEY`**: header `Authorization: <key>` (sin prefijo), API
  `https://orpheus.network/ajax.php`, patrón calcado de
  `../dieta_sonora/buscar_nuevos.py` — OJO, `../charts_orpheus` usa un
  nombre de env var (`ORPHEUS_API_KEY`) y un formato de header (`token `)
  distintos; no son intercambiables.
- **`qbittorrent_client.add_torrent()`**: no existía en ningún proyecto
  hermano — nuevo, construido sobre el mismo `_session()`/login que ya
  resolvió `artist-sync`.
- **Panel de ajustes, distinción `live`**: variables que SOLO usa `scan.py`
  (subproceso nuevo en cada sync) están marcadas `"live": True` en
  `app.py::VARS_SPEC` — cambian de efecto en el siguiente "Sincronizar" sin
  tocar el contenedor. `QB_*`/`ORPHEUS_APIKEY` NO están marcadas `live`
  porque también las usan rutas del proceso Flask de larga duración
  (`/api/availability`, `/api/orpheus/download`), fijadas una vez al
  arrancar — cambiarlas sí requiere reiniciar el contenedor.

## Related / sibling projects (same author, same conventions)

- `../artist-sync` — el "hermano" más cercano: mismo esqueleto
  (Flask + SQLite + sops + settings-panel.js), Muspy/Airsonic/qBittorrent/
  Last.fm ya resueltos ahí; la mayoría de `clients/` de este proyecto están
  copiados o extendidos directamente desde el suyo.
- `../trasvase` — origen original del patrón de panel de ajustes que
  `artist-sync` (y este proyecto) reutilizan.
- `../dieta_sonora/buscar_nuevos.py` y `comparar_con_orpheus.py` — patrón de
  la API de Orpheus (Gazelle) que sigue `clients/orpheus_client.py`.
- `../mixxx_info/src/links.py` — scraping de YouTube/Bandcamp sin API key,
  base de `clients/youtube_client.py`/`bandcamp_client.py`.
- `../bot_conciertos/handlers/artist_handlers.py` — patrón de cliente Discogs
  a copiar si se añade la fase 2.
- `../tumtumpa` — repo de orquestación real de "REPEAT-ONE" (remote GitHub
  `volteret4/repeat-one`), corre todos estos servicios hermanos vía git
  submodules + docker-compose. Este proyecto se engancharía como
  `services/discografia-gaps` (todavía no wireado — ver README.md).
