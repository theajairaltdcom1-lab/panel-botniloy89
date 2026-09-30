"""Per-panel ServisSMS client (from D:\\open code test, multi-panel version).

Each panel has its own base_url + username + password.
Auto-solves math captcha like 'What is 9 + 7 = ?'.
"""
import logging
import re

import requests

CAPTCHA_RE = re.compile(r"What is (\d+)\s*\+\s*(\d+)\s*=\s*\?")
CAPTCHA_V2_RE = re.compile(r"Solve:\s*(?:<strong>)?(\d+)\s*\+\s*(\d+)\s*=(?:</strong>)?")
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


class CooldownError(Exception):
    """v2 panel 15-second CDR cooldown."""


def detect_flavor(login_html: str) -> str:
    """'v2' (tempsms.io style), 'v1' (servis style) or 'maybe-v3' (React SPA)."""
    html = login_html or ""
    if "captcha_answer" in html:
        return "v2"
    if "What is" in html:
        return "v1"
    return "maybe-v3"


def guess_v3_api_bases(base_url: str) -> list:
    from urllib.parse import urlparse
    p = urlparse(base_url)
    cands = [base_url.rstrip("/") + "/api/v1"]
    if not p.hostname.startswith("api."):
        cands.append(f"{p.scheme}://api.{p.hostname}/api/v1")
    return cands


def detect_v3_api(base_url: str, timeout: int = 15) -> str:
    """Returns working /api/v1 base or ''."""
    for cand in guess_v3_api_bases(base_url):
        try:
            r = requests.get(cand + "/auth/captcha-config", timeout=timeout,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and "captcha" in r.text.lower():
                return cand
        except Exception:
            continue
    return ""

log = logging.getLogger("panelsms")


class LoginError(Exception):
    pass


SG_PROXY_SOURCES = True


def _candidate_sg_proxies(max_n=15):
    out = []
    try:
        r = requests.get(
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http"
            "&timeout=10000&country=SG&ssl=all&anonymity=all",
            timeout=20)
        for line in r.text.splitlines():
            line = line.strip()
            if line and ":" in line and " " not in line:
                out.append("http://" + line)
    except Exception:
        pass
    try:
        r = requests.get(
            "https://proxylist.geonode.com/api/proxy-list?limit=50"
            "&protocols=http%2Chttps&country=SG&sort_by=speed&sort_type=asc",
            timeout=20)
        for d in r.json().get("data", []) or []:
            out.append(f"http://{d['ip']}:{d['port']}")
    except Exception:
        pass
    uniq = list(dict.fromkeys(out))
    return uniq[:max_n]


def find_working_proxy(test_url: str, timeout: int = 12) -> str:
    """Free Singapore proxy খুঁজে test করে — kaj korle proxy string, নাহলে ''."""
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "Chrome/120.0.0.0 Safari/537.36")
    for p in _candidate_sg_proxies():
        try:
            r = requests.get(test_url, proxies={"http": p, "https": p},
                             timeout=timeout, headers={"User-Agent": ua})
            if r.status_code == 200 and "What is" in r.text:
                return p
        except Exception:
            continue
    return ""


def base_from_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    for tail in ("/login", "/signin"):
        if u.lower().endswith(tail):
            u = u[: -len(tail)]
    return u.rstrip("/") or u


class PanelClient:
    def __init__(self, base_url: str, username: str, password: str,
                 timeout: int = 12, proxy: str = "", flavor: str = "auto",
                 api_base: str = "", api_token: str = ""):
        self.base_url = base_from_url(base_url)
        self.username = username
        self.password = password
        self.timeout = timeout
        self.proxy = (proxy or "").strip()
        self.flavor = flavor  # 'v1', 'v2', 'v3' or 'auto'
        self.api_base = (api_base or "").rstrip("/")
        self._v3_token = (api_token or "").strip()
        self._token_fixed = bool(self._v3_token) and not self.password
        self.session = requests.Session()
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        self.session.headers["Accept-Language"] = "en-US,en;q=0.9"

    @property
    def _origin(self) -> str:
        from urllib.parse import urlparse
        p = urlparse(self.base_url)
        return f"{p.scheme}://{p.netloc}"

    @property
    def login_url(self):
        return self.base_url + "/login"

    @property
    def signin_url(self):
        return self.base_url + "/signin"

    @property
    def cdr_page_url(self):
        if self.flavor == "v2":
            return self.base_url + "/agent/SMSCDRReports"
        return self.base_url + "/agent/SMSCDRStats"

    @property
    def dash_url(self):
        return self.base_url + "/agent/SMSDashboard"

    @property
    def cdr_ajax_url(self):
        return self.base_url + "/agent/res/data_smscdr.php"

    @property
    def export_url(self):
        if self.flavor == "v2":
            return self.base_url + "/agent/res/exportsmscdr.php"
        return self.base_url + "/agent/res/exportsmscdr"

    def _solve_captcha(self, text):
        m = CAPTCHA_RE.search(text or "")
        if not m:
            m = CAPTCHA_V2_RE.search(text or "")
        if not m:
            raise LoginError("could not find captcha question on login page")
        return int(m.group(1)) + int(m.group(2))

    def _logged_out(self, r) -> bool:
        url = (getattr(r, "url", "") or "").split("?")[0]
        txt = (getattr(r, "text", "") or "").lower()
        return ("login" in url or "sign in to continue" in txt
                or ('id="username"' in txt and 'id="password"' in txt and "sign in" in txt))

    def login(self) -> bool:
        # 1) login page (browser er moto normal GET)
        r = self.session.get(
            self.login_url, timeout=self.timeout,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        )
        if self.flavor == "auto":
            self.flavor = detect_flavor(r.text)
        if self.flavor == "maybe-v3":
            self.api_base = self.api_base or detect_v3_api(self.base_url, timeout=self.timeout)
            if self.api_base:
                self.flavor = "v3"
            else:
                # protected SPA (v4) -> real browser login
                from browser_panel import browser_login
                browser_login(self.base_url, self.username, self.password)
                self.flavor = "v4"
                return True
        if self.flavor == "v4":
            from browser_panel import browser_login
            browser_login(self.base_url, self.username, self.password)
            return True
        if self.flavor == "v5":
            self.v5_test(self._v3_token or self.password)
            return True
        if self.flavor == "v3":
            return self._v3_login()
        answer = self._solve_captcha(r.text)
        # 2) form submit (browser er moto, XHR flag ছাড়া)
        if self.flavor == "v2":
            csrf = CSRF_RE.search(r.text)
            data = {"username": self.username, "password": self.password,
                    "captcha_answer": answer,
                    "csrf_token": csrf.group(1) if csrf else ""}
        else:
            data = {"username": self.username, "password": self.password, "capt": answer}
        r = self.session.post(
            self.signin_url,
            data=data,
            timeout=self.timeout,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Origin": self._origin,
                "Referer": self.login_url,
            },
        )
        if self._logged_out(r):
            raise LoginError("login rejected (ভুল user/pass বা captcha)")
        # 3) verify: ভেতরের page khule kina (session sotti kaj kore kina)
        v = self.session.get(
            self.dash_url if self.flavor == "v2" else self.cdr_page_url,
            timeout=self.timeout,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                     "Referer": self.login_url},
        )
        if self._logged_out(v):
            raise LoginError("login rejected (ভুল user/pass বা captcha)")
        return True

    def ensure_logged_in(self):
        if self.flavor == "auto":
            self.login()
            return
        if self.flavor in ("v4", "v5"):
            return  # browser page / token-per-request
        if self.flavor == "v3":
            if not self._v3_token:
                self._v3_login()
            return
        try:
            r = self.session.get(
                self.dash_url if self.flavor == "v2" else self.cdr_page_url,
                timeout=self.timeout)
        except requests.RequestException:
            r = None
        if r is None or self._logged_out(r):
            self.login()

    def test_login(self) -> bool:
        """Only username/password/captcha check (no CDR)."""
        self.ensure_logged_in()
        return True

    # ----- v3 (React REST API) -----
    def _v3_login(self) -> bool:
        if not self.api_base:
            self.api_base = detect_v3_api(self.base_url, timeout=self.timeout)
        if not self.api_base:
            raise LoginError("v3 API পাওয়া যায়নি")
        r = self.session.post(
            self.api_base + "/auth/login",
            json={"identifier": self.username, "password": self.password},
            timeout=self.timeout,
            headers={"Origin": self._origin, "Referer": self.base_url + "/login"})
        if r.status_code == 401:
            raise LoginError("login rejected (ভুল user/pass)")
        try:
            d = r.json()
        except ValueError:
            raise LoginError("login failed: " + r.text[:100])
        if not d.get("success"):
            raise LoginError("login rejected: " + str(d.get("message") or "")[:120])
        tok = (d.get("data") or {}).get("access_token", "")
        if not tok:
            raise LoginError("login failed (token নেই)")
        self._v3_token = tok
        try:  # token DB te save — restart eo login thakbe
            import sqlite3 as _sq
            _con = _sq.connect("bot.db")
            _con.execute("UPDATE panels SET api_token=? WHERE puser=? AND api_base=?",
                         (tok, self.username, self.api_base))
            _con.commit()
            _con.close()
        except Exception:
            pass
        return True

    # ----- v5 (token messages API: GET {base}/messages?token=..) -----
    def _v5_call(self, token: str, extra: dict = None):
        params = {"token": token}
        params.update(extra or {})
        url = self.api_base.rstrip("/") + "/messages"
        if url.endswith("/messages/messages"):
            url = url[: -len("/messages")]
        r = self.session.get(url, params=params, timeout=60)
        if r.status_code == 429:
            try:
                wait = int(r.json().get("retryAfterSeconds", 2))
            except Exception:
                wait = 2
            __import__("time").sleep(min(max(wait, 1), 10))
            r = self.session.get(url, params=params, timeout=60)
        if r.status_code in (401, 403):
            raise LoginError("API token invalid")
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            raise LoginError("API rejected request")
        if isinstance(data, dict) and data.get("error"):
            raise LoginError("API error: " + str(data.get("error"))[:100])
        return data

    def v5_test(self, token: str) -> bool:
        data = self._v5_call(token, {"limit": 1})
        if "records" not in data:
            raise LoginError("API token invalid")
        return True

    def _fetch_cdr_v5(self, fdate1: str, fdate2: str, fnum: str = "", limit: int = 200):
        token = self._v3_token or self.password
        data = self._v5_call(token, {"limit": min(limit, 100)})
        rows = []
        import re as _re4
        fd = _re4.sub(r"\D", "", fnum or "")
        for it in (data.get("records") or [])[:limit]:
            t = str(it.get("time") or "")
            if t and not (fdate1[:10] <= t[:10] <= fdate2[:10]):
                continue
            num = str(it.get("number") or "")
            if fd and fd not in _re4.sub(r"\D", "", num):
                continue
            rows.append([
                t, str(it.get("range") or ""), num, str(it.get("cli") or ""),
                "", str(it.get("content") or ""), "",
                str(it.get("payout") or ""), "", "",
            ])
        return {"rows": rows, "totals": None}

    def _v3_get(self, path: str, params: dict = None):
        if not self._v3_token:
            self._v3_login()
        r = self.session.get(self.api_base + path, params=params or {},
                             timeout=60,
                             headers={"Authorization": f"Bearer {self._v3_token}"})
        if r.status_code == 401 and not self._token_fixed:  # token expired -> ekbar re-login
            self._v3_login()
            r = self.session.get(self.api_base + path, params=params or {},
                                 timeout=60,
                                 headers={"Authorization": f"Bearer {self._v3_token}"})
        if r.status_code == 401 and self._token_fixed:
            raise LoginError("API token expired — notun token din")
        r.raise_for_status()
        return r.json()

    def validate_token(self) -> dict:
        """Fixed token check via /auth/me."""
        r = self.session.get(self.api_base + "/auth/me", timeout=self.timeout,
                             headers={"Authorization": f"Bearer {self._v3_token}"})
        if r.status_code == 401:
            raise LoginError("API token invalid/expired")
        r.raise_for_status()
        return r.json()

    def _fetch_cdr_v3(self, fdate1: str, fdate2: str, fnum: str = "", limit: int = 200):
        rows = []
        page = 1
        while True:
            params = {"date_from": fdate1[:10], "date_to": fdate2[:10],
                      "page": page, "page_size": 100}
            if fnum:
                params["number"] = fnum
            try:
                data = self._v3_get("/my/sms/cdr", params)
            except Exception as e:
                if "404" in str(e):
                    raise LoginError("v3 CDR endpoint নেই (role support লাগবে)")
                raise
            items = (data.get("data") or {}).get("items", []) if isinstance(data, dict) else []
            pag = (data.get("data") or {}).get("pagination", {}) if isinstance(data, dict) else {}
            for it in items:
                rows.append([
                    str(it.get("message_at") or ""), str(it.get("range_name") or ""),
                    str(it.get("number") or ""), str(it.get("cli") or ""),
                    str(it.get("client") or ""), str(it.get("sms") or ""),
                    str(it.get("currency") or ""), str(it.get("agent_payout") or ""),
                    str(it.get("client_payout") or ""),
                    str(it.get("extracted_code") or ""),
                ])
            if not pag.get("has_more") or len(rows) >= limit:
                break
            page += 1
        return {"rows": rows, "totals": None}

    def fetch_cdr(self, fdate1: str, fdate2: str, fnum: str = "", limit: int = 200):
        self.ensure_logged_in()
        if self.flavor == "v5":
            return self._fetch_cdr_v5(fdate1, fdate2, fnum, limit)
        if self.flavor == "v4":
            from browser_panel import browser_fetch_cdr
            rows = browser_fetch_cdr(self.base_url, self.username, self.password,
                                     fdate1, fdate2, limit)
            if fnum:
                import re as _re3
                fd = _re3.sub(r"\D", "", fnum)
                rows = [r for r in rows if fd in _re3.sub(r"\D", "", r[2])]
            return {"rows": rows, "totals": None}
        if self.flavor == "v3":
            return self._fetch_cdr_v3(fdate1, fdate2, fnum, limit)
        if self.flavor == "v2":
            return self._fetch_cdr_v2(fdate1, fdate2, fnum, limit)
        ajax_headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self.cdr_page_url,
            "Origin": self._origin,
        }
        rows = []
        totals = None
        offset = 0
        while True:
            params = {
                "sEcho": 1, "iColumns": 9, "sColumns": "",
                "iDisplayStart": offset, "iDisplayLength": 100,
                "sSearch": "", "bRegex": "false",
                "iSortingCols": 0,
                "fdate1": fdate1, "fdate2": fdate2,
                "frange": "", "fclient": "", "fnum": fnum, "fcli": "",
                "fgdate": "", "fgmonth": "", "fgrange": "", "fgclient": "",
                "fgnumber": "", "fgcli": "", "fg": 0,
                "_": int(__import__("time").time() * 1000),
            }
            for i in range(9):
                params[f"bSearchable_{i}"] = "true"
                params[f"bSortable_{i}"] = "true"
            r = None
            for attempt in range(3):
                r = self.session.get(self.cdr_ajax_url, params=params, timeout=60,
                                     headers=ajax_headers)
                if r.status_code not in (502, 503, 504):
                    break
                __import__("time").sleep(3 * (attempt + 1))
            if r.status_code in (502, 503, 504):
                try:
                    with open("cdr_error.html", "w", encoding="utf-8") as f:
                        f.write(f"URL: {r.url}\nSTATUS: {r.status_code}\n\n" + r.text[:3000])
                except Exception:
                    pass
            r.raise_for_status()
            try:
                data = r.json()
            except ValueError:
                raise LoginError("CDR request rejected: " + r.text[:80])
            raw = data.get("aaData", [])
            total = int(data.get("iTotalDisplayRecords") or 0)
            for item in raw:
                cells = [str(c) if c is not None else "" for c in item]
                parts = cells[0].split(",")
                if len(parts) == 13 and all(re.fullmatch(r"-?\d+(\.\d+)?", p) for p in parts):
                    totals = parts
                    continue
                rows.append(cells)
            offset += len(raw)
            if not raw or len(rows) >= total or len(rows) >= limit:
                break
        return {"rows": rows, "totals": totals}

    def _fetch_cdr_v2(self, fdate1: str, fdate2: str, fnum: str = "", limit: int = 200):
        """tempsms.io v2: date_from/date_to (YYYY-MM-DD) + DataTables 1.13 params."""
        ajax_headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self.cdr_page_url,
            "Origin": self._origin,
        }
        rows = []
        start = 0
        length = 100
        draw = 1
        while True:
            params = {
                "draw": draw, "start": start, "length": length,
                "order[0][column]": 0, "order[0][dir]": "desc",
                "search[value]": "", "search[regex]": "false",
                "date_from": fdate1[:10], "date_to": fdate2[:10],
                "range_id": "", "client_id": "", "number": fnum, "cli": "",
                "_": int(__import__("time").time() * 1000),
            }
            r = None
            for attempt in range(3):
                r = self.session.get(self.cdr_ajax_url, params=params, timeout=60,
                                     headers=ajax_headers)
                if r.status_code not in (502, 503, 504):
                    break
                __import__("time").sleep(3 * (attempt + 1))
            r.raise_for_status()
            try:
                data = r.json()
            except ValueError:
                raise LoginError("CDR request rejected: " + r.text[:80])
            if isinstance(data, dict) and data.get("cooldown", {}).get("blocked"):
                raise CooldownError("panel 15s cooldown — ektu por abar try korun")
            items = data.get("data", []) if isinstance(data, dict) else []
            total = int(data.get("recordsFiltered") or data.get("recordsTotal") or 0)
            for it in items:
                if isinstance(it, dict):
                    rows.append([
                        str(it.get("received_at") or ""), str(it.get("range") or ""),
                        str(it.get("number") or ""), str(it.get("cli") or ""),
                        str(it.get("client") or ""), str(it.get("sms") or ""),
                        str(it.get("currency") or ""), str(it.get("my_payout") or ""),
                        str(it.get("client_payout") or ""),
                    ])
                elif isinstance(it, list):
                    rows.append([str(c) if c is not None else "" for c in it])
            start += len(items)
            draw += 1
            if not items or (total and len(rows) >= total) or len(rows) >= limit:
                break
        return {"rows": rows, "totals": None}

    def _page_csrf(self) -> str:
        r = self.session.get(self.cdr_page_url, timeout=self.timeout,
                             headers={"Referer": self.dash_url})
        m = CSRF_RE.search(r.text or "")
        return m.group(1) if m else ""

    def export_csv(self, fdate1: str, fdate2: str, fnum: str = "") -> bytes:
        self.ensure_logged_in()
        if self.flavor in ("v3", "v4", "v5"):
            raise LoginError("v3/v4/v5 panel export শীঘ্রই আসছে")
        if self.flavor == "v2":
            data = {
                "csrf_token": self._page_csrf(),
                "date_from": fdate1[:10], "date_to": fdate2[:10],
                "range_id": "", "client_id": "", "number": fnum, "cli": "", "search": "",
            }
            r = self.session.post(
                self.export_url, data=data, timeout=60,
                headers={"Referer": self.cdr_page_url, "Origin": self._origin})
            r.raise_for_status()
            return r.content
        data = {
            "fdate1": fdate1, "fdate2": fdate2, "frange": "", "fclient": "",
            "fnum": fnum, "fcli": "", "fgdate": "", "fgmonth": "", "fgrange": "",
            "fgclient": "", "fgnumber": "", "fgcli": "",
        }
        r = self.session.post(self.export_url, data=data, timeout=60)
        r.raise_for_status()
        return r.content

    def check(self) -> str:
        """Live check -> 'OK ...' or raises."""
        self.ensure_logged_in()
        today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        res = self.fetch_cdr(f"{today} 00:00:00", f"{today} 23:59:59", limit=5)
        return f"OK, {len(res['rows'])} row(s) today"
