"""v4: protected React panels via real Chromium (Playwright Async API).

One dedicated thread runs its own asyncio loop; all browser ops
execute there (thread-safe for the bot's thread pool).
"""
import asyncio
import concurrent.futures
import queue
import threading

_tasks: "queue.Queue[tuple]" = queue.Queue()
_state: dict = {}
_started = False
_start_lock = threading.Lock()


def _worker():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def init():
        from playwright.async_api import async_playwright
        _state["pw"] = await async_playwright().start()
        try:
            _state["browser"] = await _state["pw"].chromium.launch(
                channel="chrome", headless=True)
        except Exception:
            try:
                _state["browser"] = await _state["pw"].chromium.launch(headless=True)
            except Exception:
                import subprocess as _sp
                import sys as _sys
                await loop.run_in_executor(
                    None, lambda: _sp.run(
                        [_sys.executable, "-m", "playwright", "install", "chromium"],
                        timeout=600))
                _state["browser"] = await _state["pw"].chromium.launch(headless=True)
        _state["pages"] = {}
        _state["loop"] = loop

    loop.run_until_complete(init())

    async def serve():
        while True:
            fn, args, fut = await loop.run_in_executor(None, _tasks.get)
            try:
                res = await fn(*args)
                fut.set_result(res)
            except BaseException as e:  # noqa: BLE001
                fut.set_exception(e)

    loop.create_task(serve())
    loop.run_forever()


def _start():
    global _started
    with _start_lock:
        if _started:
            return
        threading.Thread(target=_worker, daemon=True, name="browser-worker").start()
        _started = True


def _run(coro_fn, *args, timeout: int = 240):
    _start()
    fut: concurrent.futures.Future = concurrent.futures.Future()
    _tasks.put((coro_fn, args, fut))
    return fut.result(timeout)


def _pages():
    return _state["pages"]


async def _get_page(key: str):
    pages = _pages()
    rec = pages.get(key)
    if rec is None or rec.is_closed():
        rec = await _state["browser"].new_page(viewport={"width": 1400, "height": 900})
        pages[key] = rec
    return rec


async def _goto(pg, url: str, timeout: int = 60000):
    try:
        await pg.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception as e:
        if "ERR_ABORTED" not in str(e) and "net::" not in str(e):
            raise


async def _do_login(base_url: str, username: str, password: str) -> bool:
    key = f"{base_url}|{username}"
    pg = await _get_page(key)
    await _goto(pg, base_url.rstrip("/") + "/login")
    await pg.wait_for_timeout(3000)
    if "/login" not in (pg.url or ""):
        return True
    users = await pg.query_selector_all(
        'input[aria-label="Username"], input[name="username"], input[placeholder="Username"]')
    pwds = await pg.query_selector_all(
        'input[aria-label="Password"], input[name="password"], '
        'input[type="password"], input[placeholder="Password"]')
    if not users or not pwds:
        raise RuntimeError("login form পাওয়া যায়নি")
    await users[0].fill(username)
    await pwds[0].fill(password)
    try:
        await pg.click('button[type="submit"]', timeout=5000)
    except Exception:
        await pg.keyboard.press("Enter")
    await pg.wait_for_timeout(7000)
    if "/login" in (pg.url or ""):
        raise RuntimeError("login rejected (ভুল user/pass)")
    return True


async def _do_fetch(base_url: str, username: str, password: str,
                    fdate1: str, fdate2: str, limit: int):
    key = f"{base_url}|{username}"
    pg = await _get_page(key)
    if "/login" in (pg.url or ""):
        await _do_login(base_url, username, password)
        pg = await _get_page(key)
    saved = {}
    seen = []

    def _cap(r):
        if "/api/cdrs?" in r.url:
            seen.append(r)

    pg.on("response", _cap)
    try:
        await _goto(pg, base_url.rstrip("/") + "/cdrs")
        await pg.wait_for_timeout(5000)
        if "/login" in (pg.url or ""):
            await _do_login(base_url, username, password)
            pg = await _get_page(key)
            await _goto(pg, base_url.rstrip("/") + "/cdrs")
            await pg.wait_for_timeout(5000)
        inputs = await pg.query_selector_all("input[type='text']")
        if len(inputs) >= 2:
            await inputs[0].fill(fdate1)
            await inputs[1].fill(fdate2)
            await pg.keyboard.press("Escape")
            try:
                await pg.click("text=Show Report", force=True, timeout=8000)
            except Exception:
                pass
            await pg.wait_for_timeout(7000)
    finally:
        try:
            pg.remove_listener("response", _cap)
        except Exception:
            pass
    for r in seen:
        try:
            saved["body"] = await r.text()
            break
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
                    timeout=300)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"browser fetch fail: {str(e)[:120]}")
