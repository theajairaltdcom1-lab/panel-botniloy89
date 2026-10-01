"""v4: protected React panels (e.g. Lamix) via real Chrome (Playwright).

Login + CDR report are driven in-page so the app's own request
signing/encryption keeps working.

IMPORTANT: sync Playwright is NOT thread-safe — every browser op runs
on ONE dedicated worker thread via a task queue.
"""
import queue
import threading

_tasks: "queue.Queue[tuple]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()

_pw = None
_browser = None
_pages: dict = {}  # key -> {"page": Page, "password": str}


def _start_worker():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(target=_loop, daemon=True, name="browser-worker")
        t.start()
        _worker_started = True


def _loop():
    while True:
        fn, args, fut = _tasks.get()
        try:
            fut["ok"] = True
            fut["res"] = fn(*args)
        except BaseException as e:  # noqa: BLE001
            fut["ok"] = False
            fut["res"] = e
        finally:
            fut["done"].set()


def _run(fn, *args, timeout: int = 180):
    _start_worker()
    fut = {"done": threading.Event(), "ok": False, "res": None}
    _tasks.put((fn, args, fut))
    if not fut["done"].wait(timeout):
        raise TimeoutError("browser busy/timeout")
    if not fut["ok"]:
        raise fut["res"]
    return fut["res"]


def _ensure():
    global _pw, _browser
    if _browser is None:
        try:
            from playwright.sync_api import sync_playwright
            _pw = sync_playwright().start()
            try:
                _browser = _pw.chromium.launch(channel="chrome", headless=True)
            except Exception:
                try:
                    _browser = _pw.chromium.launch(headless=True)
                except Exception:
                    import subprocess as _sp
                    import sys as _sys
                    _sp.run([_sys.executable, "-m", "playwright", "install",
                             "chromium"], timeout=600)
                    _browser = _pw.chromium.launch(headless=True)
        except Exception:
            _browser = None
            raise
    return _browser


def _reset():
    global _browser, _pw, _pages
    _pages = {}
    try:
        if _browser is not None:
            _browser.close()
    except Exception:
        pass
    try:
        if _pw is not None:
            _pw.stop()
    except Exception:
        pass
    _browser = None
    _pw = None


def _goto(pg, url: str, timeout: int = 60000):
    try:
        pg.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception as e:
        # SPA redirect abort is fine
        if "ERR_ABORTED" not in str(e) and "net::" not in str(e):
            raise


def _get_page(key: str):
    b = _ensure()
    rec = _pages.get(key)
    if rec is None:
        try:
            pg = b.new_page(viewport={"width": 1400, "height": 900})
        except Exception:
            _reset()
            b = _ensure()
            pg = b.new_page(viewport={"width": 1400, "height": 900})
        rec = {"page": pg}
        _pages[key] = rec
    return rec["page"]


def _do_login(base_url: str, username: str, password: str) -> bool:
    key = f"{base_url}|{username}"
    try:
        pg = _get_page(key)
    except Exception as e:
        raise RuntimeError(f"browser start fail: {str(e)[:100]}")
    try:
        _goto(pg, base_url.rstrip("/") + "/login")
        pg.wait_for_timeout(3000)
        if "/login" not in (pg.url or ""):
            return True
        users = pg.query_selector_all(
            'input[aria-label="Username"], input[name="username"]')
        pwds = pg.query_selector_all(
            'input[aria-label="Password"], input[name="password"], input[type="password"]')
        if not users or not pwds:
            raise RuntimeError("login form পাওয়া যায়নি")
        users[0].fill(username)
        pwds[0].fill(password)
        try:
            pg.click('button[type="submit"]', timeout=5000)
        except Exception:
            pg.keyboard.press("Enter")
        pg.wait_for_timeout(7000)
        if "/login" in (pg.url or ""):
            raise RuntimeError("login rejected (ভুল user/pass)")
        return True
    except RuntimeError:
        raise
    except Exception as e:
        _pages.pop(key, None)
        raise RuntimeError(f"browser login fail: {str(e)[:120]}")


def _do_fetch(base_url: str, username: str, password: str,
              fdate1: str, fdate2: str, limit: int):
    key = f"{base_url}|{username}"
    pg = _get_page(key)
    if "/login" in (pg.url or ""):
        _do_login(base_url, username, password)
        pg = _get_page(key)
    saved = {}

    def on_resp(r):
        if "/api/cdrs?" in r.url:
            try:
                saved["body"] = r.text()
            except Exception:
                pass

    pg.on("response", lambda r: on_resp(r) if "/api/cdrs?" in r.url else None)
    try:
        _goto(pg, base_url.rstrip("/") + "/cdrs")
        pg.wait_for_timeout(5000)
        if "/login" in (pg.url or ""):  # session expired
            _do_login(base_url, username, password)
            pg = _get_page(key)
            _goto(pg, base_url.rstrip("/") + "/cdrs")
            pg.wait_for_timeout(5000)
        inputs = pg.query_selector_all("input[type='text']")
        if len(inputs) >= 2:
            inputs[0].fill(fdate1)
            inputs[1].fill(fdate2)
            pg.keyboard.press("Escape")
            try:
                pg.click("text=Show Report", force=True, timeout=8000)
            except Exception:
                pass
            pg.wait_for_timeout(7000)
    finally:
        try:
            pg.remove_listener("response", on_resp)
        except Exception:
            pass
    import json as _json
    try:
        data = _json.loads(saved.get("body") or "{}")
    except Exception:
        raise RuntimeError("CDR response পড়া যায়নি")
    rows = []
    for it in (data.get("rows") or [])[:limit]:
        rows.append([
            str(it.get("receivedAt") or ""), str(it.get("rangeName") or ""),
            str(it.get("receivedNumber") or ""), str(it.get("senderCli") or ""),
            str(it.get("clientUsername") or ""), str(it.get("content") or ""),
            str(it.get("currency") or ""), str(it.get("agentPayout") or ""),
            str(it.get("clientPayout") or ""), "",
        ])
    return rows


def browser_login(base_url: str, username: str, password: str) -> bool:
    try:
        return _run(_do_login, base_url, username, password)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"browser fail: {str(e)[:120]}")


def browser_fetch_cdr(base_url: str, username: str, password: str,
                      fdate1: str, fdate2: str, limit: int = 100):
    try:
        return _run(_do_fetch, base_url, username, password, fdate1, fdate2, limit,
                    timeout=240)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"browser fetch fail: {str(e)[:120]}")
