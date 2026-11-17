# discografia-gaps

Para cada artista de tu "universo" (**Muspy** seguidos ∪ **Airsonic**
biblioteca ∪ **Last.fm** por encima de un umbral de scrobbles opcional),
calcula su discografía completa (Álbumes + EPs, vía **MusicBrainz**
release-groups) y marca qué discos ya tienes frente a los que te faltan. Para
un disco que falta, bajo demanda, comprueba si está disponible en **Orpheus**
(tracker privado, descarga vía **qBittorrent** con confirmación explícita),
**YouTube** o **Bandcamp**.

## Setup

```bash
pip install -r requirements.txt
```

Variables de entorno (via `.env` local, o `.encrypted.env` + sops si se
integra en tumtumpa):

```bash
# Muspy — uno de los tres orígenes del universo de artistas
MUSPY_USERNAME=...
MUSPY_PASSWORD=...

# Airsonic / Subsonic — otro origen del universo, y fuente de "have"
AIRSONIC_URL=http://localhost:4040
AIRSONIC_USER=admin
AIRSONIC_PASSWORD=...
AIRSONIC_API_VERSION=1.15.0

# Last.fm — filtro OPCIONAL: añade al universo artistas con >= N scrobbles.
# LASTFM_MIN_PLAYCOUNT=0 (por defecto) desactiva esta fuente por completo.
LASTFM_API_KEY=...
LASTFM_USERNAME=...
LASTFM_MIN_PLAYCOUNT=0
LASTFM_SCROBBLES_DB=/data/lastfm_stats.db   # espejo compartido de tumtumpa, si existe

# qBittorrent WebUI — fuente de "have" (tags FLAC) y destino de las descargas
# confirmadas desde la web
QB_HOST=host.docker.internal
QB_PORT=8080
QB_USER=admin
QB_PASS=...
QB_CATEGORY=              # opcional, para "have": vacío = todos los torrents
QB_DOWNLOAD_CATEGORY=     # opcional, categoria con la que se añaden descargas nuevas
QB_REMOTE_PATH=           # ej. /downloads — solo si qBittorrent corre en su propio contenedor

# MusicBrainz — discografia completa por artista
MB_EMAIL=tu@email.com

# Orpheus.network (Gazelle) — busca disponibilidad de descarga de los discos que faltan
ORPHEUS_APIKEY=...

SETTINGS_PASSWORD=...     # protege el panel ⚙ de la web
```

Cualquier fuente sin credenciales se omite sin dar error (Orpheus/YouTube/
Bandcamp se comprueban solo bajo demanda desde la web, no en `scan.py`).

## Uso

```bash
python scan.py                              # universo + discografia + have
python scan.py --only universe
python scan.py --only discography,have
python scan.py --only discography --force-discography   # reescanea toda la discografia

python app.py             # sirve la web en 0.0.0.0:5000
```

También puede lanzarse desde la propia web (botón "↻ Sincronizar").

## Cómo funciona

- **Universo de artistas** = Muspy ∪ Airsonic ∪ Last.fm (si el umbral de
  scrobbles está activado). `scan.py` reemplaza por completo los artistas de
  cada fuente en cada sync (mismo criterio que `presence` en `artist-sync`),
  así que un artista que desaparece de todas las fuentes se poda solo.
- **Discografía** = release-groups de tipo Álbum/EP de MusicBrainz,
  excluyendo directos/recopilatorios/remixes/BSOs (ver
  `_EXCLUDED_SECONDARY_TYPES` en `clients/musicbrainz_client.py`). Se
  re-sincroniza cada 30 días por artista salvo `--force-discography`.
- **"Have"** se marca cruzando el título normalizado del release-group contra
  los álbumes de Airsonic (`getArtist.view`) y los álbumes vistos en
  qBittorrent (tag `album` de un FLAC por carpeta de torrent) — coincidencia
  por título exacto normalizado, sin fuzzy matching todavía.
- **Disponibilidad (Orpheus/YouTube/Bandcamp) es perezosa**: solo se consulta
  cuando expandes un disco que falta en la web, y se cachea 7 días para no
  repetir scraping ni gastar el rate-limit de Orpheus en cada visita.
- **Descargar es siempre una acción explícita**: el botón "Descargar" de un
  torrent concreto de Orpheus pide confirmación y solo entonces llama a
  `qbittorrent_client.add_torrent()` — nada se descarga automáticamente.

## Pendiente de wireado en tumtumpa

Este proyecto todavía no está enganchado como submodule de `../tumtumpa`
(`services/discografia-gaps`) ni tiene entrada en su `docker-compose.yml` —
hace falta crear el repo en GitHub y decidir el puerto host antes de ese
paso. Ver `CLAUDE.md` para el resto de contexto de arquitectura.

## Instalación con Docker Compose

```bash
cp .env.example .env
```

Rellena `.env` (credenciales y carpetas de tu equipo) y arranca:

```bash
docker compose up -d --build
```

Los datos que genera (bases, cachés) se quedan en esta misma carpeta, fuera de git.

## Actualizaciones automáticas

El `docker-compose.yml` trae su propia [Ofelia](https://github.com/mcuadros/ofelia), que lanza dentro del contenedor los mismos trabajos y a las mismas horas que en REPEAT-ONE (formato con segundos: `seg min hora día mes día-semana`, hora de `TZ`, por defecto Europe/Madrid):

| Trabajo | Cuándo | Qué lanza |
|---|---|---|
| `discografia-gaps-scan` | `0 30 5 * * *` | `python3 scan.py --only universe,have` |
| `discografia-gaps-discography` | `0 35 5 * * 0` | `python3 scan.py --only discography` |

Para cambiar una hora, edita su etiqueta `ofelia.job-exec.<trabajo>.schedule` en `docker-compose.yml` y vuelve a hacer `docker compose up -d`. Para lanzarlo a mano: `docker compose exec <servicio> <orden>`. Para no tener actualizaciones automáticas: `docker compose stop ofelia`.

Esta Ofelia solo ve los contenedores de este repo (etiqueta `repeat-one.ofelia`), así que puedes tener varios módulos instalados por separado sin que se pisen. Necesita el socket de Docker en solo lectura.
