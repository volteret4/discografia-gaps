"""Cliente de la API de Muspy (https://muspy.com/api/1) — auth basica user/password."""
import requests

BASE_URL = "https://muspy.com/api/1"


class MuspyError(Exception):
    pass


def get_user_id(username, password):
    resp = requests.get(f"{BASE_URL}/user", auth=(username, password), timeout=10)
    if resp.status_code != 200:
        raise MuspyError(f"No se pudo obtener el user id de Muspy: {resp.status_code} {resp.text}")
    return resp.json()["userid"]


def list_followed_artists(username, password, user_id):
    """Devuelve [{mbid, name, sort_name, disambiguation}, ...]."""
    resp = requests.get(f"{BASE_URL}/artists/{user_id}", auth=(username, password), timeout=20)
    if resp.status_code != 200:
        raise MuspyError(f"Error listando artistas de Muspy: {resp.status_code} {resp.text}")
    return resp.json()


def follow_artist(username, password, user_id, mbid):
    url = f"{BASE_URL}/artists/{user_id}/{mbid}"
    resp = requests.put(url, auth=(username, password), timeout=10)
    if resp.status_code not in (200, 201):
        raise MuspyError(f"Error siguiendo artista en Muspy: {resp.status_code} {resp.text}")
    return True


def unfollow_artist(username, password, user_id, mbid):
    url = f"{BASE_URL}/artists/{user_id}/{mbid}"
    resp = requests.delete(url, auth=(username, password), timeout=10)
    if resp.status_code not in (200, 204):
        raise MuspyError(f"Error dejando de seguir artista en Muspy: {resp.status_code} {resp.text}")
    return True
