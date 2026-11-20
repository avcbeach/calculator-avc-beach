"""
github_publish.py
-----------------
Upload / read files in a GitHub repository through the GitHub contents API, so the public
rankings page (GitHub Pages) can be refreshed straight from the app.

Needs a fine-grained personal access token with "Contents: Read and write" on that ONE repo,
kept in Streamlit secrets (never in the code). Uses only the standard library.
"""

import base64
import json
import urllib.error
import urllib.request

API = "https://api.github.com"


def _call(method: str, url: str, token: str, body: dict = None):
    req = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "avc-rankings-app",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        if e.code == 404 and method == "GET":
            return None
        detail = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"GitHub {e.code}: {detail}") from None


def read_file(repo: str, path: str, branch: str, token: str):
    """(text, sha) of a file, or (None, None) if it does not exist yet."""
    d = _call("GET", f"{API}/repos/{repo}/contents/{path}?ref={branch}", token)
    if not d or "content" not in d:
        return None, None
    return base64.b64decode(d["content"]).decode("utf-8"), d["sha"]


def write_file(repo: str, path: str, branch: str, token: str, text: str, message: str):
    """Create or update a file (one commit). Skips the commit when the content is unchanged."""
    old, sha = read_file(repo, path, branch, token)
    if old == text:
        return False
    body = {"message": message, "branch": branch,
            "content": base64.b64encode(text.encode("utf-8")).decode()}
    if sha:
        body["sha"] = sha
    _call("PUT", f"{API}/repos/{repo}/contents/{path}", token, body)
    return True
