"""bot.db backup/restore via GitHub repo file (DBBackup/bot.db).

Railway filesystem ephemeral — restart e data(f) jate na jay:
- boot: GitHub theke bot.db download (thakle)
- proti 120s: change hole push
"""
import base64
import json
import logging
import os
import time
import urllib.request

log = logging.getLogger("dbsync")

DB_PATH = "bot.db"
REMOTE_PATH = "DBBackup/bot.db"


def _cfg():
    try:
        import config as _c
        pat = os.environ.get("GH_PAT", "") or getattr(_c, "GH_PAT", "")
        repo = os.environ.get("GH_REPO", "") or getattr(_c, "GH_REPO", "")
        branch = os.environ.get("GH_BRANCH", "") or getattr(_c, "GH_BRANCH", "master")
        return pat, repo, branch
    except Exception:
        return "", "", "master"


def _api(path: str, method: str = "GET", data=None):
    pat, repo, branch = _cfg()
    if not pat or not repo:
        return None
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, body, {
        "Authorization": f"Bearer {pat}", "User-Agent": "panel-bot",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"})
    if method != "GET":
        req.get_method = lambda: method
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        log.warning("dbsync api fail: %s", str(e)[:100])
        return None


def pull_db() -> bool:
    """Boot e remote DB namau (thakle)."""
    if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
        return False  # local data ache — overwrite noy
    d = _api(REMOTE_PATH)
    if not d or not d.get("content"):
        return False
    try:
        raw = base64.b64decode(d["content"])
        if len(raw) < 100:
            return False
        with open(DB_PATH, "wb") as f:
            f.write(raw)
        try:
            import sqlite3
            con = sqlite3.connect(DB_PATH)
            con.execute("SELECT 1 FROM users LIMIT 1")
            con.close()
        except Exception:
            os.remove(DB_PATH)
            return False
        log.info("dbsync: DB restored from GitHub")
        return True
    except Exception as e:
        log.warning("dbsync pull fail: %s", str(e)[:100])
        return False


def push_db(force: bool = False) -> bool:
    """Local DB GitHub e tulau."""
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        return False
    try:
        with open(DB_PATH, "rb") as f:
            raw = f.read()
    except Exception:
        return False
    cur = _api(REMOTE_PATH)
    sha = (cur or {}).get("sha", "")
    payload = {"message": f"db backup {time.strftime('%Y-%m-%d %H:%M:%S')}",
               "content": base64.b64encode(raw).decode(),
               "branch": _cfg()[2]}
    if sha:
        payload["sha"] = sha
    r = _api(REMOTE_PATH, method="PUT", data=payload)
    ok = bool(r and r.get("content"))
    if ok:
        log.info("dbsync: DB pushed to GitHub")
    return ok


_last_push_mtime = 0.0


async def dbsync_loop(interval: int = 120):
    """Background: change hole push."""
    global _last_push_mtime
    import asyncio
    await asyncio.sleep(30)
    while True:
        try:
            if os.path.exists(DB_PATH):
                mt = os.path.getmtime(DB_PATH)
                if mt != _last_push_mtime:
                    import concurrent.futures as _cf
                    loop = asyncio.get_running_loop()
                    with _cf.ThreadPoolExecutor(max_workers=1) as ex:
                        ok = await loop.run_in_executor(ex, push_db)
                    if ok:
                        _last_push_mtime = os.path.getmtime(DB_PATH)
        except Exception as e:
            log.warning("dbsync loop: %s", str(e)[:100])
        await asyncio.sleep(interval)
