"""
site_publish.py
---------------
Publish the public Asian Rankings page to AVC's own server (asianvolleyball.com/playground/rankings/)
through publish.php in that folder. Same read_file / write_file shape as github_publish.py.

Streamlit secrets:

    [playground]
    url = "https://asianvolleyball.com/playground/rankings/publish.php"
    key = "the key in publish-key.php on the server"
"""

import requests


def read_file(url: str, key: str, name: str):
    """Current text of a published file, or None if it does not exist yet."""
    r = requests.get(url, params={"file": name}, headers={"X-Publish-Key": key}, timeout=30)
    data = _json(r)
    return data.get("content") if data.get("exists") else None


def write_file(url: str, key: str, name: str, text: str) -> bool:
    """Saves one file. Returns True if it changed, False if the server already had the same page."""
    r = requests.post(url, json={"file": name, "content": text}, headers={"X-Publish-Key": key}, timeout=60)
    return bool(_json(r).get("changed"))


def _json(r):
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"Server answered {r.status_code} without JSON - is publish.php in place?") from None
    if not data.get("ok"):
        raise RuntimeError(f"Server: {data.get('error', r.status_code)}")
    return data
