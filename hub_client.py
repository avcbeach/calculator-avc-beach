"""
hub_client.py
-------------
Talks to the Beach Hub API (Apps Script web app over the "Beach Hub — Master Data" sheet),
so this app picks events from the same list as every other AVC beach app.

Needs two lines in Streamlit secrets (Manage app ▸ Settings ▸ Secrets, or .streamlit/secrets.toml):

    [hub]
    url = "https://script.google.com/macros/s/…/exec"
    key = "the API_KEY from the Beach Hub API project"
"""

import re
from datetime import date, datetime

import requests
import streamlit as st

FIVB_RE = re.compile(r"\b(BPT|FIVB|Beach Pro Tour|Futures|Challenge|Elite ?16|World Championships?|World Series)\b", re.I)


def config():
    """(url, key) from secrets, or None when the Hub is not set up for this app."""
    try:
        h = st.secrets["hub"]
        url, key = str(h["url"]).strip(), str(h["key"]).strip()
        return (url, key) if url and key else None
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _get(url: str, key: str, type_: str) -> list:
    r = requests.get(url, params={"key": key, "type": type_}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Beach Hub: {data.get('error', 'unknown error')}")
    return data.get("data") or []


def _d(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def events(include_fivb: bool = False) -> list:
    """Events from the Hub, oldest first. Each: event_id, name, city, country, start (date), end (date),
    gender, category, status, vis_nos (list of VIS tournament numbers)."""
    cfg = config()
    if not cfg:
        return []
    out = []
    for e in _get(cfg[0], cfg[1], "events"):
        if e.get("status") == "Cancelled":
            continue
        fivb = e.get("category") == "FIVB" or bool(FIVB_RE.search(e.get("name") or ""))
        if fivb and not include_fivb:
            continue
        out.append({
            **e,
            "start": _d(e.get("start_date")),
            "end": _d(e.get("end_date")) or _d(e.get("start_date")),
            "vis_nos": vis_numbers(e.get("vis_no")),
        })
    return out


def vis_numbers(value) -> list:
    """'12345, 12346' -> ['12345', '12346']. Ignores anything that is not a plain number."""
    s = str(value or "").strip()
    if s.startswith("{") or s.startswith("["):
        return []
    return re.findall(r"\d{3,}", s)


def set_vis_no(event_id: str, vis_nos: list) -> None:
    """Saves the VIS tournament number(s) for one event in the Hub."""
    cfg = config()
    if not cfg:
        raise RuntimeError("Beach Hub is not set up (secrets [hub] url/key).")
    r = requests.post(cfg[0], json={"key": cfg[1], "action": "setVisNo", "event_id": event_id,
                                     "vis_no": ", ".join(vis_nos)}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Beach Hub: {data.get('error', 'could not save')}")
    _get.clear()


def label(e: dict) -> str:
    place = ", ".join(x for x in (e.get("city"), e.get("country")) if x)
    s, en = e.get("start"), e.get("end")
    if s and en and s != en:
        when = f"{s:%d %b} – {en:%d %b %Y}" if s.year == en.year else f"{s:%d %b %Y} – {en:%d %b %Y}"
    else:
        when = f"{s:%d %b %Y}" if s else "no date"
    return f"{e['name']}" + (f" · {place}" if place else "") + f" · {when}"
