# --- Config: ENV first, then local_settings.py (gitignored) ---
import os as _os

BOT_TOKEN = _os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = []
_admins = _os.environ.get("ADMIN_IDS", "")
if _admins:
    ADMIN_IDS = [int(x) for x in _admins.split(",") if x.strip().isdigit()]

try:
    import local_settings as _ls  # noqa: E402
    if not BOT_TOKEN:
        BOT_TOKEN = getattr(_ls, "BOT_TOKEN", "")
    if not ADMIN_IDS:
        ADMIN_IDS = list(getattr(_ls, "ADMIN_IDS", []))
except ImportError:
    pass

# DB backup (GitHub) — Railway reset eo data thakbe
GH_PAT = _os.environ.get("GH_PAT", "")
GH_REPO = _os.environ.get("GH_REPO", "theajairaltdcom1-lab/panel-botniloy89")
GH_BRANCH = _os.environ.get("GH_BRANCH", "master")

# OTP forward group (bot ke group e add kore admin dite hobe)
OTP_GROUP = _os.environ.get("OTP_GROUP", "@bssyrxteamotp")
# Koto second por por panel check hobe
POLL_SECONDS = int(_os.environ.get("POLL_SECONDS", "10"))
# Referral reward + withdraw limits
REF_REWARD = float(_os.environ.get("REF_REWARD", "5"))
MIN_WITHDRAW = float(_os.environ.get("MIN_WITHDRAW", "10"))
