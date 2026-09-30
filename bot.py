"""
NEXOVIA / EARNIVERSE style Panel Bot
Screenshot er button layout onujayi banano.

Run:
  pip install -r requirements.txt
  python bot.py   (config.py te BOT_TOKEN + ADMIN_IDS bosan)
"""
import asyncio
import sqlite3
import time
from datetime import datetime

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

from config import BOT_TOKEN, ADMIN_IDS
from panelsms import PanelClient, LoginError, base_from_url, find_working_proxy, CooldownError

DB = "bot.db"

# ---------- DB ----------
def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    c = con.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        balance REAL DEFAULT 0, banned INTEGER DEFAULT 0, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sub_admins(
        user_id INTEGER PRIMARY KEY, added_by INTEGER, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS panels(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE,
        details TEXT DEFAULT '', status TEXT DEFAULT 'ON',
        url TEXT DEFAULT '', puser TEXT DEFAULT '', ppass TEXT DEFAULT '',
        created_at TEXT)""")
    # migration for old DB
    for col in ("url TEXT DEFAULT ''", "puser TEXT DEFAULT ''", "ppass TEXT DEFAULT ''",
                "proxy TEXT DEFAULT ''", "flavor TEXT DEFAULT 'auto'",
                "api_base TEXT DEFAULT ''", "api_token TEXT DEFAULT ''"):
        try:
            c.execute(f"ALTER TABLE panels ADD COLUMN {col}")
        except Exception:
            pass
    c.execute("""CREATE TABLE IF NOT EXISTS numbers(
        id INTEGER PRIMARY KEY AUTOINCREMENT, panel_id INTEGER,
        number TEXT, country TEXT DEFAULT '', emoji TEXT DEFAULT '',
        status TEXT DEFAULT 'AVAILABLE', created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS servers(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE,
        url TEXT DEFAULT '', status TEXT DEFAULT 'ON', created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS country_emoji(
        code TEXT PRIMARY KEY, emoji TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS transactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        amount REAL, type TEXT, reason TEXT DEFAULT '',
        admin_id INTEGER, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS pending(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        type TEXT, details TEXT, status TEXT DEFAULT 'PENDING',
        created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS otp_groups(
        chat_id TEXT PRIMARY KEY, title TEXT DEFAULT '', created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS stock(
        id INTEGER PRIMARY KEY AUTOINCREMENT, service TEXT, number TEXT UNIQUE,
        country TEXT DEFAULT '', created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, number TEXT,
        service TEXT DEFAULT '', country TEXT DEFAULT '', status TEXT DEFAULT 'pending',
        otp TEXT DEFAULT '', created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS referrals(
        id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER,
        invited_id INTEGER UNIQUE, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS tempmails(
        telegram_id INTEGER PRIMARY KEY, login TEXT, domain TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS withdrawals(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL,
        address TEXT DEFAULT '', status TEXT DEFAULT 'pending', created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY, value TEXT DEFAULT '')""")
    c.execute("""CREATE TABLE IF NOT EXISTS master_admins(
        user_id INTEGER PRIMARY KEY, added_by INTEGER, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS services(
        code TEXT PRIMARY KEY, label TEXT DEFAULT '')""")
    for _s, _l in (("telegram", "✈️ Telegram"), ("whatsapp", "💚 WhatsApp"),
                   ("facebook", "📘 Facebook"), ("instagram", "📸 Instagram")):
        try:
            c.execute("INSERT OR IGNORE INTO services(code,label) VALUES(?,?)", (_s, _l))
        except Exception:
            pass
    con.commit()
    con.close()

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ---------- helpers ----------
def is_main_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def is_sub_admin(uid: int) -> bool:
    con = db()
    r = con.execute("SELECT 1 FROM sub_admins WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return r is not None

def is_admin(uid: int) -> bool:
    return is_main_admin(uid) or is_master_admin(uid) or is_sub_admin(uid)

def ensure_user(u):
    con = db()
    row = con.execute("SELECT * FROM users WHERE user_id=?", (u.id,)).fetchone()
    if not row:
        con.execute("INSERT INTO users(user_id,username,first_name,created_at) VALUES(?,?,?,?)",
                    (u.id, u.username or "", u.first_name or "", now()))
        con.commit()
    else:
        con.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
                    (u.username or "", u.first_name or "", u.id))
        con.commit()
    con.close()

def get_setting(key: str, default: str = "") -> str:
    con = db()
    try:
        r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    except Exception:
        r = None
    con.close()
    return r["value"] if r and r["value"] != "" else default


def set_setting(key: str, value: str):
    con = db()
    try:
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
        con.commit()
    except Exception:
        pass
    con.close()


def is_master_admin(uid: int) -> bool:
    con = db()
    try:
        r = con.execute("SELECT 1 FROM master_admins WHERE user_id=?", (uid,)).fetchone()
    except Exception:
        r = None
    con.close()
    return r is not None


def can_manage_admins(uid: int) -> bool:
    return is_main_admin(uid) or is_master_admin(uid)


def get_services() -> list:
    con = db()
    try:
        rows = con.execute("SELECT code, label FROM services ORDER BY code").fetchall()
    except Exception:
        rows = []
    con.close()
    if not rows:
        return [("telegram", "✈️ Telegram"), ("whatsapp", "💚 WhatsApp"),
                ("facebook", "📘 Facebook"), ("instagram", "📸 Instagram")]
    return [(r["code"], r["label"] or r["code"]) for r in rows]


def is_banned(uid: int) -> bool:
    con = db()
    r = con.execute("SELECT banned FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return bool(r and r["banned"])

def resolve_user_id(text: str):
    """Numeric ID or @username -> user_id. Returns None if not found."""
    t = (text or "").strip()
    if t.startswith("@"):
        t = t[1:]
    if t.isdigit():
        return int(t)
    if not t:
        return None
    con = db()
    r = con.execute("SELECT user_id FROM users WHERE LOWER(username)=?", (t.lower(),)).fetchone()
    con.close()
    return r["user_id"] if r else None

def get_balance(uid: int) -> float:
    con = db()
    r = con.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
    con.close()
    return float(r["balance"]) if r else 0.0

def add_balance(uid: int, amount: float, reason: str, admin_id: int):
    con = db()
    con.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
    con.execute("INSERT INTO transactions(user_id,amount,type,reason,admin_id,created_at) VALUES(?,?,?,?,?,?)",
                (uid, amount, "ADD" if amount >= 0 else "DEDUCT", reason, admin_id, now()))
    con.commit()
    con.close()

# ---------- keyboards (screenshot layout) ----------
def admin_menu():
    npr = get_setting("numbers_per_request", "1")
    cm = get_setting("checker_mode", "ON")
    pd = get_setting("prefix_display", "ON")
    pl = get_setting("prefix_length", "7")
    ov = get_setting("otp_visibility", "show")
    of = get_setting("otp_format", "v0.2")
    cm_e = "🟢" if cm == "ON" else "🔴"
    pd_e = "🟢" if pd == "ON" else "🔴"
    ov_t = "Show OTP" if ov == "show" else "Hide OTP"
    return ReplyKeyboardMarkup([
        ["➕ Add Panel", "❌ Remove Panel"],
        ["➕ Add V2 Panel"],
        ["📋 Panel List", "📊 Panel Status"],
        ["📦 Add Numbers", "🗑️ Remove Numbers"],
        ["💻 Servers", "👥 Pending"],
        ["📈 Stats"],
        ["👥 Users", "👀 Country Emoji"],
        ["🧑‍✈️ Sub Admins", "🚫 Ban User"],
        ["✅ Unban User", "📢 Broadcast"],
        ["📨 OTP Groups"],
        ["🔌 API Panels"],
        ["📱 Number Stock", "💸 Withdrawals"],
        ["⚙️ Admin Panel"],
        ["💰 Balance Manage", "👁️ User Balance History"],
        ["📱 User Panel"],
        ["➕ Add Master Admin", "❌ Remove Master Admin"],
        ["👑 Master Admin List"],
        ["⚙️ Config Setup"],
        [f"🔢 Number Count (Current: {npr})"],
        ["➕ Create New Service", "🎁 Service List"],
        [f"{cm_e} Checker Mode: {cm}"],
        [f"{pd_e} 👀 Prefix Display: {pd}"],
        [f"📏 Prefix Length: {pl} digits"],
        [f"👁️ OTP Visibility: {ov_t}"],
        ["📊 Checker Status"],
        [f"📄 OTP Format: {of}"],
        ["📞 Main Menu"],
    ], resize_keyboard=True)

def user_menu():
    return ReplyKeyboardMarkup([
        ["📱 Numbers", "👤 Profile"],
        ["🎁 Referral", "🎧 Support"],
        ["🌍 Country", "📈 Live Traffic"],
        ["📧 Temp Mail"],
    ], resize_keyboard=True)

def cancel_menu():
    return ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)

# ---------- start ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    first = False
    con = db()
    if not con.execute("SELECT 1 FROM users WHERE user_id=?", (u.id,)).fetchone():
        first = True
    con.close()
    ensure_user(u)
    ctx.user_data.clear()
    # referral: /start <referrer_id>
    if first and ctx.args:
        try:
            ref = int(ctx.args[0])
            if ref != u.id:
                import config as _cfg2
                try:
                    _rw = float(get_setting("ref_reward", str(_cfg2.REF_REWARD)))
                except ValueError:
                    _rw = 5
                con = db()
                try:
                    con.execute("INSERT INTO referrals(referrer_id,invited_id,created_at) VALUES(?,?,?)",
                                (ref, u.id, now()))
                    con.commit()
                    con.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (_rw, ref))
                    con.execute("INSERT INTO transactions(user_id,amount,type,reason,admin_id,created_at) VALUES(?,?,?,?,?,?)",
                                (ref, _rw, "ADD", "referral reward", 0, now()))
                    con.commit()
                except Exception:
                    pass
                con.close()
        except (ValueError, TypeError):
            pass
    if is_banned(u.id):
        await update.message.reply_text("⛔ You are banned.")
        return
    if is_admin(u.id):
        await update.message.reply_text("Select an option below 👇", reply_markup=admin_menu())
    else:
        await update.message.reply_text(
            f"👋 Welcome {u.first_name}!\n\nSelect an option below 👇",
            reply_markup=user_menu())

async def admin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    ctx.user_data.clear()
    await update.message.reply_text("Select an option below 👇", reply_markup=admin_menu())


async def main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    if is_admin(update.effective_user.id):
        await update.message.reply_text("📞 Main Menu", reply_markup=admin_menu())
    else:
        await update.message.reply_text("📞 Main Menu", reply_markup=user_menu())

def need_admin(update):
    return is_admin(update.effective_user.id)

# ---------- text router ----------
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ensure_user(u)
    if is_banned(u.id):
        await update.message.reply_text("⛔ You are banned.")
        return
    text = (update.message.text or "").strip()
    state = ctx.user_data.get("state")

    # global
    if text in ("📞 Main Menu", "/start"):
        await main_menu(update, ctx)
        return
    if text == "❌ Cancel":
        ctx.user_data.clear()
        await main_menu(update, ctx)
        return

    # continue multi-step flows first
    if state:
        await handle_state(update, ctx, text)
        return

    admin = need_admin(update)

    # ----- shared -----
    if text == "📊 Panel Status" or text == "🌍 Panel Status":
        await cmd_panel_status(update, ctx); return
    if text == "📋 Panel List":
        await cmd_panel_list(update, ctx); return
    if text == "📈 Stats" or text == "📊 Stats":
        await cmd_stats(update, ctx); return
    if text == "🌍 Users" or text == "👥 Users":
        await cmd_users(update, ctx, admin); return
    if text == "📞 Pending":
        await cmd_pending(update, ctx, admin); return
    if text == "👥 Pending" and admin:
        await cmd_pending(update, ctx, True); return
    if text == "💰 My Balance":
        await update.message.reply_text(f"💰 Your balance: {get_balance(u.id)}"); return
    if text == "📜 My History":
        await cmd_my_history(update, ctx); return
    if text == "📱 Numbers":
        await cmd_numbers(update, ctx); return
    if text == "🌍 Country":
        await cmd_numbers(update, ctx); return
    if text == "👤 Profile":
        await cmd_profile(update, ctx); return
    if text == "🎁 Referral":
        await cmd_referral(update, ctx); return
    if text == "📧 Temp Mail":
        await cmd_tempmail(update, ctx); return
    if text == "📈 Live Traffic":
        await cmd_traffic(update, ctx); return
    if text == "🎧 Support":
        await update.message.reply_text("🎧 Support: https://t.me/yaufee"); return

    if not admin:
        await update.message.reply_text("❌ Admin only. /start", reply_markup=user_menu())
        return

    # ----- admin only -----
    if text == "➕ Add Panel":
        ctx.user_data["state"] = "add_panel_name"
        ctx.user_data.pop("force_flavor", None)
        await update.message.reply_text("Panel name পাঠান:", reply_markup=cancel_menu())
    if text == "➕ Add V2 Panel":
        ctx.user_data["state"] = "add_panel_name"
        ctx.user_data["force_flavor"] = "v2"
        await update.message.reply_text("V2 Panel name পাঠান:", reply_markup=cancel_menu())
    elif text == "❌ Remove Panel":
        await cmd_remove_panel_list(update, ctx)
    elif text == "📦 Add Numbers":
        ctx.user_data["state"] = "add_numbers_panel"
        await show_panel_choice(update, "কোন Panel এ number add হবে? Panel name লিখুন:")
    elif text == "🗑️ Remove Numbers":
        ctx.user_data["state"] = "rm_numbers_panel"
        await show_panel_choice(update, "কোন Panel থেকে number remove হবে? Panel name লিখুন:")
    elif text == "💻 Servers":
        await cmd_servers(update, ctx)
    elif text == "👀 Country Emoji":
        await cmd_country_list(update, ctx)
        ctx.user_data["state"] = "country_emoji"
        await update.message.reply_text("Format: `CODE=EMOJI` (যেমন `BD=🇧🇩`)\nএক লাইনে একটা করে পাঠান।", reply_markup=cancel_menu(), parse_mode="Markdown")
    elif text == "🧑‍✈️ Sub Admins":
        await cmd_subadmins(update, ctx)
    elif text == "🚫 Ban User":
        ctx.user_data["state"] = "ban"
        await update.message.reply_text("Ban করতে ID বা @username পাঠান:", reply_markup=cancel_menu())
    elif text == "✅ Unban User":
        ctx.user_data["state"] = "unban"
        await update.message.reply_text("Unban করতে ID বা @username পাঠান:", reply_markup=cancel_menu())
    elif text == "📢 Broadcast":
        ctx.user_data["state"] = "broadcast"
        await update.message.reply_text("Broadcast message পাঠান:", reply_markup=cancel_menu())
    elif text == "📨 OTP Groups":
        await cmd_otpgroups(update, ctx)
    elif "API Panels" in text:
        await cmd_apipanels(update, ctx)
    elif "Admin Panel" in text:
        await cmd_adminpanel(update, ctx)
    elif text == "📱 User Panel":
        await update.message.reply_text("👤 User Panel (admin view):", reply_markup=user_menu())
    elif text.startswith("➕ Add Master"):
        if not is_main_admin(update.effective_user.id):
            await update.message.reply_text("❌ Only main admin."); return
        ctx.user_data["state"] = "master_add"
        await update.message.reply_text("Master Admin ID বা @username পাঠান:", reply_markup=cancel_menu())
    elif text.startswith("❌ Remove Master"):
        if not is_main_admin(update.effective_user.id):
            await update.message.reply_text("❌ Only main admin."); return
        ctx.user_data["state"] = "master_remove"
        await update.message.reply_text("Remove করতে ID বা @username পাঠান:", reply_markup=cancel_menu())
    elif "Master Admin List" in text:
        await cmd_masterlist(update, ctx)
    elif "Config Setup" in text:
        await cmd_config(update, ctx)
    elif text.startswith("🔢 Number Count"):
        ctx.user_data["state"] = "numcount"
        await update.message.reply_text(f"Ekbare koyta number dibe? (akhon {get_setting('numbers_per_request', '1')}):",
                                        reply_markup=cancel_menu())
    elif text.startswith("➕ Create New Service"):
        ctx.user_data["state"] = "svc_new"
        await update.message.reply_text("Format: `code=Label` (যেমন `imo=📹 IMO`):",
                                        reply_markup=cancel_menu(), parse_mode="Markdown")
    elif "Service List" in text:
        svcs = get_services()
        kb = [[InlineKeyboardButton(f"❌ {label}", callback_data=f"svc_del:{code}")]
              for code, label in svcs]
        await update.message.reply_text("🎁 Service List:\n" + "\n".join(f"• {l} (`{c}`)" for c, l in svcs),
                                        parse_mode="Markdown",
                                        reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    elif "Checker Mode" in text:
        cur = get_setting("checker_mode", "ON")
        set_setting("checker_mode", "OFF" if cur == "ON" else "ON")
        await update.message.reply_text(f"Checker Mode → {get_setting('checker_mode', 'ON')}",
                                        reply_markup=admin_menu())
    elif "Prefix Display" in text:
        cur = get_setting("prefix_display", "ON")
        set_setting("prefix_display", "OFF" if cur == "ON" else "ON")
        await update.message.reply_text(f"Prefix Display → {get_setting('prefix_display', 'ON')}",
                                        reply_markup=admin_menu())
    elif "Prefix Length" in text:
        cur = int(get_setting("prefix_length", "7"))
        nxt = {5: 6, 6: 7, 7: 8, 8: 5}.get(cur, 7)
        set_setting("prefix_length", str(nxt))
        await update.message.reply_text(f"Prefix Length → {nxt} digits", reply_markup=admin_menu())
    elif "OTP Visibility" in text:
        cur = get_setting("otp_visibility", "show")
        set_setting("otp_visibility", "hide" if cur == "show" else "show")
        await update.message.reply_text(f"OTP Visibility → {get_setting('otp_visibility', 'show')}",
                                        reply_markup=admin_menu())
    elif "Checker Status" in text:
        await cmd_checker_status(update, ctx)
    elif "OTP Format" in text:
        cur = get_setting("otp_format", "v0.2")
        set_setting("otp_format", "v0.1" if cur == "v0.2" else "v0.2")
        await update.message.reply_text(f"OTP Format → {get_setting('otp_format', 'v0.2')}",
                                        reply_markup=admin_menu())
    elif text == "📱 Number Stock":
        await cmd_stock(update, ctx)
    elif text == "💸 Withdrawals":
        await cmd_withdrawals(update, ctx)
    elif text == "💰 Balance Manage":
        ctx.user_data["state"] = "bal_id"
        await update.message.reply_text("ID বা @username পাঠান:", reply_markup=cancel_menu())
    elif text == "👁️ User Balance History":
        ctx.user_data["state"] = "hist_id"
        await update.message.reply_text("ID বা @username পাঠান:", reply_markup=cancel_menu())
    else:
        await update.message.reply_text("Select an option below 👇", reply_markup=admin_menu())

# ---------- state flows ----------
async def handle_state(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str):
    u = update.effective_user
    st = ctx.user_data.get("state")

    if st == "add_panel_name":
        ctx.user_data["pname"] = text
        ctx.user_data["state"] = "add_panel_url"
        await update.message.reply_text("Panel URL পাঠান (যেমন https://...):", reply_markup=cancel_menu())
    elif st == "add_panel_url":
        ctx.user_data["purl"] = text
        ctx.user_data["state"] = "add_panel_user"
        await update.message.reply_text("Panel এর User / Username পাঠান:", reply_markup=cancel_menu())
    elif st == "add_panel_user":
        ctx.user_data["puser"] = text
        ctx.user_data["state"] = "add_panel_pass"
        await update.message.reply_text("Panel এর Password পাঠান:", reply_markup=cancel_menu())
    elif st == "add_panel_pass":
        ctx.user_data["ppass"] = text
        ctx.user_data["state"] = "add_panel_details"
        await update.message.reply_text("Details লিখুন (অথবা `-`):", reply_markup=cancel_menu())
    elif st == "add_panel_details":
        pname = ctx.user_data.pop("pname")
        purl = ctx.user_data.pop("purl", "")
        puser = ctx.user_data.pop("puser", "")
        ppass = ctx.user_data.pop("ppass", "")
        details = "" if text == "-" else text
        await update.message.reply_text("⏳ Panel login test হচ্ছে...", reply_markup=cancel_menu())

        def _probe(proxy=""):
            ff = ctx.user_data.get("force_flavor", "auto")
            c = PanelClient(purl, puser, ppass, proxy=proxy, flavor=ff)  # ek session reuse
            c.test_login()
            try:
                return ("ok", c.check(), c.flavor, c.api_base)
            except Exception as e:
                return ("cdr_fail", str(e), c.flavor, c.api_base)

        flavor = "auto"
        api_base = ""
        used_proxy = ""
        try:
            status, info, flavor, api_base = await asyncio.to_thread(_probe)
        except (LoginError, Exception) as e:
            ctx.user_data.clear()
            await update.message.reply_text(
                f"❌ Panel add হয়নি:\n{str(e)[:200]}\n\nURL/User/Password check করে আবার চেষ্টা করুন.",
                reply_markup=admin_menu())
            return
        if status == "ok":
            extra = f"\n\n🟢 {pname} — Login Success, {info.replace('OK,', '').strip()}"
        elif "403" in info:
            extra = (f"\n\n🟡 {pname} — Login Success, kintu report blocked "
                     f"(403 Forbidden)। OTP forward kaj na korte pare.")
        else:
            extra = f"\n\n🟡 {pname} — Login Success, kintu report check fail: {info[:150]}"
        con = db()
        try:
            con.execute("INSERT INTO panels(name,details,url,puser,ppass,proxy,flavor,api_base,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (pname, details, purl, puser, ppass, used_proxy, flavor, api_base, now()))
            con.commit()
            ptag = " (🛰️ SG proxy)" if used_proxy else ""
            msg = f"✅ Panel added: {pname}{ptag}\n🔗 {purl}\n👤 {puser}{extra}"
        except sqlite3.IntegrityError:
            msg = "❌ এই নামে panel আগেই আছে।"
        con.close()
        ctx.user_data.clear()
        await update.message.reply_text(msg, reply_markup=admin_menu())

    elif st == "add_numbers_panel":
        con = db()
        p = con.execute("SELECT * FROM panels WHERE name=?", (text,)).fetchone()
        con.close()
        if not p:
            await update.message.reply_text("❌ Panel পাওয়া যায়নি। সঠিক name দিন:")
            return
        ctx.user_data["panel_id"] = p["id"]
        ctx.user_data["state"] = "add_numbers_list"
        await update.message.reply_text(
            "Numbers পাঠান (প্রতি লাইনে ১টা)।\nFormat: `number | COUNTRY` যেমন:\n`8801XXXXXXXXX | BD`",
            reply_markup=cancel_menu())

    elif st == "add_numbers_list":
        pid = ctx.user_data["panel_id"]
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        con = db()
        n = 0
        for line in lines:
            if "|" in line:
                num, code = [x.strip().upper() for x in line.split("|", 1)]
            else:
                num, code = line.strip(), ""
            er = con.execute("SELECT emoji FROM country_emoji WHERE code=?", (code,)).fetchone() if code else None
            emoji = er["emoji"] if er else ""
            con.execute("INSERT INTO numbers(panel_id,number,country,emoji,created_at) VALUES(?,?,?,?,?)",
                        (pid, num, code, emoji, now()))
            n += 1
        con.commit(); con.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ {n} টা number added.", reply_markup=admin_menu())

    elif st == "rm_numbers_panel":
        con = db()
        p = con.execute("SELECT * FROM panels WHERE name=?", (text,)).fetchone()
        con.close()
        if not p:
            await update.message.reply_text("❌ Panel পাওয়া যায়নি:")
            return
        con = db()
        rows = con.execute("SELECT id,number FROM numbers WHERE panel_id=? LIMIT 30", (p["id"],)).fetchall()
        con.close()
        if not rows:
            ctx.user_data.clear()
            await update.message.reply_text("এই panel এ number নেই।", reply_markup=admin_menu())
            return
        ctx.user_data["panel_id"] = p["id"]
        ctx.user_data["state"] = "rm_numbers_id"
        lst = "\n".join(f"{r['id']} - {r['number']}" for r in rows)
        await update.message.reply_text(f"Delete করতে Number ID পাঠান:\n{lst}", reply_markup=cancel_menu())

    elif st == "rm_numbers_id":
        con = db()
        con.execute("DELETE FROM numbers WHERE id=?", (text,))
        con.commit()
        left = con.execute("SELECT changes()").fetchone()[0]
        con.close()
        ctx.user_data.clear()
        await update.message.reply_text("✅ Deleted." if left else "❌ ID পাওয়া যায়নি।", reply_markup=admin_menu())

    elif st == "country_emoji":
        con = db()
        n = 0
        for line in text.split("\n"):
            if "=" in line:
                code, emoji = [x.strip() for x in line.split("=", 1)]
                if code:
                    con.execute("INSERT OR REPLACE INTO country_emoji(code,emoji) VALUES(?,?)", (code.upper(), emoji))
                    n += 1
        con.commit(); con.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ {n} টা country emoji saved.", reply_markup=admin_menu())

    elif st == "ban":
        target = resolve_user_id(text)
        if not target:
            await update.message.reply_text("❌ User পাওয়া যায়নি। ID বা @username দিন (সে আগে bot এ /start দিক)।"); return
        con = db()
        con.execute("INSERT OR IGNORE INTO users(user_id,created_at) VALUES(?,?)", (target, now()))
        con.execute("UPDATE users SET banned=1 WHERE user_id=?", (target,))
        con.commit(); con.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"🚫 Banned: {target}", reply_markup=admin_menu())

    elif st == "unban":
        target = resolve_user_id(text)
        if not target:
            await update.message.reply_text("❌ User পাওয়া যায়নি। ID বা @username দিন।"); return
        con = db()
        con.execute("UPDATE users SET banned=0 WHERE user_id=?", (target,))
        con.commit(); con.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Unbanned: {target}", reply_markup=admin_menu())

    elif st == "broadcast":
        con = db()
        users = con.execute("SELECT user_id FROM users WHERE banned=0").fetchall()
        con.close()
        sent = 0
        for r in users:
            try:
                await ctx.bot.send_message(r["user_id"], f"📢 Broadcast:\n\n{text}")
                sent += 1
            except Exception:
                pass
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Broadcast sent: {sent} users", reply_markup=admin_menu())

    elif st == "otpgroup_add":
        import re as _re3
        target = text.strip()
        # t.me link hole username/ID ber koro
        m = _re3.search(r"t\.me/(?:c/(\d+)|(\+[\w-]+)|([A-Za-z0-9_]{5,}))", target)
        if m:
            if m.group(1):  # private: t.me/c/123 -> -100123
                target = "-100" + m.group(1)
            elif m.group(2):  # invite link: ID lagbe
                ctx.user_data.clear()
                await update.message.reply_text(
                    "❌ Invite link (`t.me/+...`) diye add hoy na।\n"
                    "Group er numeric ID den (-100...) — @MissRose_bot er `/id` command e paben, "
                    "ba public hole @username den.",
                    reply_markup=admin_menu())
                return
            else:
                target = "@" + m.group(3)
        try:
            chat = await ctx.bot.get_chat(target)
            cid = str(chat.id)
            title = chat.title or getattr(chat, "username", "") or cid
            con = db()
            con.execute("INSERT OR REPLACE INTO otp_groups(chat_id,title,created_at) VALUES(?,?,?)",
                        (cid, title, now()))
            con.commit(); con.close()
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ OTP group added: {title} (`{cid}`)",
                                            parse_mode="Markdown", reply_markup=admin_menu())
        except Exception:
            await update.message.reply_text(
                "❌ Group পাওয়া যায়নি। Bot ke group e add + admin করে @username / link / ID পাঠান।",
                reply_markup=cancel_menu())

    elif st == "bal_id":
        target = resolve_user_id(text)
        if not target:
            await update.message.reply_text("❌ User পাওয়া যায়নি। ID বা @username দিন।"); return
        ctx.user_data["target"] = target
        ctx.user_data["state"] = "bal_amt"
        await update.message.reply_text("Amount পাঠান (যোগ করতে `+100`, কাটতে `-50`):", reply_markup=cancel_menu())

    elif st == "bal_amt":
        try: amt = float(text.replace("+", ""))
        except ValueError:
            await update.message.reply_text("❌ Valid amount দিন:"); return
        target = ctx.user_data["target"]
        con = db()
        con.execute("INSERT OR IGNORE INTO users(user_id,created_at) VALUES(?,?)", (target, now()))
        con.commit(); con.close()
        add_balance(target, amt, "manual by admin", u.id)
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Balance updated. {target} → {get_balance(target)}", reply_markup=admin_menu())

    elif st == "hist_id":
        target = resolve_user_id(text)
        if not target:
            await update.message.reply_text("❌ User পাওয়া যায়নি। ID বা @username দিন।"); return
        con = db()
        rows = con.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 20", (target,)).fetchall()
        con.close()
        ctx.user_data.clear()
        if not rows:
            await update.message.reply_text("No history.", reply_markup=admin_menu())
        else:
            msg = f"👁️ History of {target}:\n\n" + "\n".join(
                f"{r['created_at']} | {r['amount']} | {r['reason']}" for r in rows)
            await update.message.reply_text(msg, reply_markup=admin_menu())

    elif st == "stock_add_svc":
        t = text.strip().lower()
        alias = {"tg": "telegram", "wa": "whatsapp", "fb": "facebook", "ig": "instagram"}
        svc = alias.get(t, t)
        if svc not in [s for s, _ in get_services()]:
            await update.message.reply_text("❌ Service name দিন: telegram / whatsapp / facebook / instagram")
            return
        ctx.user_data["svc"] = svc
        ctx.user_data["state"] = "stock_add_nums"
        await update.message.reply_text(
            f"{svc_label(svc)} — numbers পাঠান (প্রতি লাইনে ১টা, + সহ):",
            reply_markup=cancel_menu())

    elif st == "stock_add_nums":
        import re as _re2
        svc = ctx.user_data.get("svc", "telegram")
        nums = []
        for line in text.split("\n"):
            for tok in _re2.split(r"[\s,;]+", line.strip()):
                d = _re2.sub(r"\D", "", tok)
                if len(d) >= 7:
                    nums.append("+" + d)
        con = db()
        added = 0
        for n in dict.fromkeys(nums):
            try:
                con.execute("INSERT OR IGNORE INTO stock(service,number,country,created_at) VALUES(?,?,?,?)",
                            (svc, n, country_of_number(n), now()))
                added += 1
            except Exception:
                pass
        con.commit(); con.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Stock added: {added} ({svc_label(svc)})",
                                        reply_markup=admin_menu())

    elif st == "wd_amt":
        import config as _cfg3
        try:
            _minwd = float(get_setting("min_withdraw", str(_cfg3.MIN_WITHDRAW)))
        except ValueError:
            _minwd = 10
        try:
            amt = float(text)
        except ValueError:
            await update.message.reply_text("❌ Valid amount দিন:"); return
        if amt < _minwd:
            await update.message.reply_text(f"❌ Minimum withdraw: {_minwd}"); return
        if amt > get_balance(u.id):
            await update.message.reply_text("❌ Balance কম আছে।"); return
        ctx.user_data["wd_amt"] = amt
        ctx.user_data["state"] = "wd_addr"
        await update.message.reply_text("Wallet address পাঠান:", reply_markup=cancel_menu())

    elif st == "wd_addr":
        amt = ctx.user_data.pop("wd_amt", 0)
        con = db()
        con.execute("INSERT INTO withdrawals(user_id,amount,address,created_at) VALUES(?,?,?,?)",
                    (u.id, amt, text.strip(), now()))
        con.commit(); con.close()
        add_balance(u.id, -amt, "withdraw request", u.id)
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Withdraw request: {amt}\nAdmin approve করলে পাঠানো হবে।",
                                        reply_markup=user_menu() if not need_admin(update) else admin_menu())

    elif st == "master_add":
        if not is_main_admin(u.id):
            ctx.user_data.clear()
            await update.message.reply_text("❌ Only main admin.", reply_markup=admin_menu())
            return
        target = resolve_user_id(text)
        if not target:
            await update.message.reply_text("❌ User পাওয়া যায়নি। ID বা @username দিন।"); return
        con = db()
        con.execute("INSERT OR REPLACE INTO master_admins(user_id,added_by,created_at) VALUES(?,?,?)",
                    (target, u.id, now()))
        con.commit(); con.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Master Admin added: {target}", reply_markup=admin_menu())

    elif st == "master_remove":
        if not is_main_admin(u.id):
            ctx.user_data.clear()
            await update.message.reply_text("❌ Only main admin.", reply_markup=admin_menu())
            return
        target = resolve_user_id(text)
        if not target:
            await update.message.reply_text("❌ User পাওয়া যায়নি। ID বা @username দিন।"); return
        con = db()
        try:
            con.execute("DELETE FROM master_admins WHERE user_id=?", (target,))
            con.commit()
        except Exception:
            pass
        con.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Master Admin removed: {target}", reply_markup=admin_menu())

    elif st == "numcount":
        try:
            n = int(text)
            assert 1 <= n <= 20
        except (ValueError, AssertionError):
            await update.message.reply_text("❌ 1-20 er moddhe number din:"); return
        set_setting("numbers_per_request", str(n))
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Number Count → {n}", reply_markup=admin_menu())

    elif st == "svc_new":
        if "=" in text:
            code, label = [x.strip() for x in text.split("=", 1)]
        else:
            await update.message.reply_text("❌ Format: `code=Label`"); return
        code = code.lower().replace(" ", "")
        if not code or not label:
            await update.message.reply_text("❌ Format: `code=Label`"); return
        con = db()
        try:
            con.execute("INSERT OR REPLACE INTO services(code,label) VALUES(?,?)", (code, label))
            con.commit(); msg = f"✅ Service created: {label} (`{code}`)"
        except Exception as e:
            msg = f"❌ Error: {str(e)[:100]}"
        con.close()
        ctx.user_data.clear()
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=admin_menu())

    elif st == "cfg_value":
        key = ctx.user_data.get("cfg_key", "")
        try:
            v = float(text)
            assert v >= 0
        except (ValueError, AssertionError):
            await update.message.reply_text("❌ Valid number din:"); return
        set_setting(key, str(int(v) if v == int(v) else v))
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ {key} → {get_setting(key, '')}", reply_markup=admin_menu())

    elif st == "api_add_base":
        import urllib.parse as _up2
        raw = text.strip()
        tok = ""
        base = raw.rstrip("/")
        if "token=" in raw:
            try:
                q = _up2.urlparse(raw)
                tok = _up2.parse_qs(q.query).get("token", [""])[0]
                base = f"{q.scheme}://{q.netloc}{q.path}".rstrip("/")
            except Exception:
                pass
        if base.endswith("/messages"):
            base = base[: -len("/messages")]
        ctx.user_data["api_base"] = base
        if tok:
            ctx.user_data["api_token_url"] = tok
        else:
            ctx.user_data.pop("api_token_url", None)
        ctx.user_data["state"] = "api_add_user"
        await update.message.reply_text("API User / Username পাঠান:", reply_markup=cancel_menu())

    elif st == "api_add_user":
        ctx.user_data["api_user"] = text.strip()
        ctx.user_data["state"] = "api_add_pass"
        await update.message.reply_text("API Password বা API Token পাঠান:", reply_markup=cancel_menu())

    elif st == "api_add_pass":
        api_base = ctx.user_data.pop("api_base", "")
        api_user = ctx.user_data.pop("api_user", "")
        secret = text.strip()
        pname = f"API {api_user}"
        await update.message.reply_text("⏳ API login test হচ্ছে...", reply_markup=cancel_menu())

        is_token = secret.startswith("eyJ") and len(secret) > 50
        url_tok = ctx.user_data.pop("api_token_url", "")

        def _probe3():
            if url_tok:  # messages URL theke token (v5)
                c = PanelClient(api_base, api_user, "", flavor="v5",
                                api_base=api_base, api_token=url_tok)
                c.v5_test(url_tok)
                return c.check(), url_tok, "v5"
            if is_token:
                c = PanelClient(api_base, api_user, "", flavor="v3",
                                api_base=api_base, api_token=secret)
                c.validate_token()
                return c.check(), secret, "v3"
            # opaque token (v5 style) password field e dile
            if len(secret) > 15:
                try:
                    c = PanelClient(api_base, api_user, "", flavor="v5",
                                    api_base=api_base, api_token=secret)
                    c.v5_test(secret)
                    return c.check(), secret, "v5"
                except Exception:
                    pass
            c = PanelClient(api_base, api_user, secret, flavor="v3", api_base=api_base)
            c.test_login()
            return c.check(), "", "v3"

        try:
            ok_msg, used_token, flav = await asyncio.to_thread(_probe3)
            extra = f"\n\n🟢 {pname} — Login Success, {ok_msg.replace('OK,', '').strip()}"
        except Exception as e:
            ctx.user_data.clear()
            await update.message.reply_text(
                f"❌ API panel add হয়নি:\n{str(e)[:200]}",
                reply_markup=admin_menu())
            return
        con = db()
        try:
            con.execute("INSERT INTO panels(name,details,url,puser,ppass,proxy,flavor,api_base,api_token,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (pname, "API panel", api_base, api_user, "" if (is_token or flav == "v5") else secret,
                         "", flav, api_base, used_token, now()))
            con.commit()
            ttag = " (🔑 token)" if (is_token or flav == "v5") else ""
            msg = f"✅ API Panel added{ttag}: {pname}\n🌐 {api_base}\n👤 {api_user}{extra}"
        except sqlite3.IntegrityError:
            msg = "❌ এই নামে panel আগেই আছে।"
        con.close()
        ctx.user_data.clear()
        await update.message.reply_text(msg, reply_markup=admin_menu())

    elif st == "server_add":
        if "=" in text:
            name, url = [x.strip() for x in text.split("=", 1)]
        else:
            name, url = text.strip(), ""
        con = db()
        try:
            con.execute("INSERT INTO servers(name,url,created_at) VALUES(?,?,?)", (name, url, now()))
            con.commit(); msg = f"✅ Server added: {name}"
        except sqlite3.IntegrityError:
            msg = "❌ এই নামে server আছে।"
        con.close()
        ctx.user_data.clear()
        await update.message.reply_text(msg, reply_markup=admin_menu())

    elif st == "server_remove":
        con = db()
        con.execute("DELETE FROM servers WHERE name=?", (text,))
        con.commit()
        left = con.execute("SELECT changes()").fetchone()[0]
        con.close()
        ctx.user_data.clear()
        await update.message.reply_text("✅ Removed." if left else "❌ পাওয়া যায়নি।", reply_markup=admin_menu())

    elif st == "subadmin_add":
        target = resolve_user_id(text)
        if not target:
            await update.message.reply_text("❌ User পাওয়া যায়নি। ID বা @username দিন (সে আগে bot এ /start দিক)।"); return
        if is_main_admin(target):
            await update.message.reply_text("সে already main admin.")
            return
        con = db()
        con.execute("INSERT OR REPLACE INTO sub_admins(user_id,added_by,created_at) VALUES(?,?,?)", (target, u.id, now()))
        con.commit(); con.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Sub-admin added: {target}", reply_markup=admin_menu())

    elif st == "subadmin_remove":
        target = resolve_user_id(text)
        if not target:
            await update.message.reply_text("❌ User পাওয়া যায়নি। ID বা @username দিন।"); return
        con = db()
        con.execute("DELETE FROM sub_admins WHERE user_id=?", (target,))
        con.commit(); con.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Sub-admin removed: {target}", reply_markup=admin_menu())

    else:
        ctx.user_data.clear()
        await main_menu(update, ctx)

# ---------- commands ----------
async def show_panel_choice(update, prompt):
    con = db()
    rows = con.execute("SELECT name FROM panels").fetchall()
    con.close()
    names = ", ".join(r["name"] for r in rows) if rows else "(কোনো panel নেই)"
    await update.message.reply_text(f"{prompt}\nPanels: {names}", reply_markup=cancel_menu())

async def cmd_panel_list(update, ctx):
    con = db()
    rows = con.execute("SELECT * FROM panels ORDER BY id DESC").fetchall()
    con.close()
    if not rows:
        await update.message.reply_text("কোনো panel নেই।")
        return
    admin = is_admin(update.effective_user.id)
    # text with url/user (password hidden for normal users until Get Login)
    lines = []
    for r in rows:
        try: url = r["url"]
        except Exception: url = ""
        try: pu = r["puser"]
        except Exception: pu = ""
        if admin:
            try: pp = r["ppass"]
            except Exception: pp = ""
            lines.append(f"• {r['name']} [{r['status']}]\n  🔗 {url or '-'}\n  👤 {pu or '-'} | 🔑 {pp or '-'}\n  📝 {r['details'] or '-'}")
        else:
            lines.append(f"• {r['name']} [{r['status']}]\n  🔗 {url or '-'}")
    text = "📋 Panel List (unlimited):\n\n" + "\n\n".join(lines)
    kb = []
    for r in rows:
        if admin:
            kb.append([InlineKeyboardButton(f"❌ {r['name']}", callback_data=f"delpanel:{r['id']}"),
                       InlineKeyboardButton(f"🔄 {r['status']}", callback_data=f"togpanel:{r['id']}")])
            kb.append([InlineKeyboardButton(f"📊 {r['name']} CDR", callback_data=f"panelstats:{r['id']}"),
                       InlineKeyboardButton(f"📥 CSV", callback_data=f"panelcsv:{r['id']}")])
        else:
            if r["status"] == "ON":
                kb.append([InlineKeyboardButton(f"🔑 {r['name']} Login", callback_data=f"getlogin:{r['id']}"),
                           InlineKeyboardButton("📊 CDR", callback_data=f"panelstats:{r['id']}")])
    if kb:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text)


def _row_proxy(r) -> str:
    try:
        return r["proxy"] or ""
    except Exception:
        return ""


def _row_flavor(r) -> str:
    try:
        return r["flavor"] or "auto"
    except Exception:
        return ""


def _row_api(r) -> str:
    try:
        return r["api_base"] or ""
    except Exception:
        return ""


def _row_token(r) -> str:
    try:
        return r["api_token"] or ""
    except Exception:
        return ""


def _row_otp(cells) -> str:
    """v3 server code (col 10) prefer, নাহলে extract."""
    if len(cells) > 9 and cells[9]:
        return str(cells[9])
    return extract_otp(" ".join(cells[:9]))


_CLIENTS: dict = {}


def _get_client(pid, url: str, pu: str, pp: str, proxy: str = "",
                flavor: str = "auto", api_base: str = "", api_token: str = "") -> PanelClient:
    """Ek panel = ek session (bar-bar login noy)."""
    key = (pid, url, pu, proxy, flavor, api_base, (api_token or "")[:20])
    c = _CLIENTS.get(key)
    if c is None:
        c = PanelClient(url, pu, pp, proxy=proxy, flavor=flavor,
                        api_base=api_base, api_token=api_token)
        _CLIENTS[key] = c
    return c


def _live_panel_check(pid: int) -> str:
    """Blocking live login+CDR check for one panel. Returns display line."""
    con = db()
    r = con.execute("SELECT * FROM panels WHERE id=?", (pid,)).fetchone()
    con.close()
    if not r:
        return "🔴 deleted panel"
    url = r["url"] if "url" in r.keys() else ""
    pu = r["puser"] if "puser" in r.keys() else ""
    pp = r["ppass"] if "ppass" in r.keys() else ""
    if not url or not pu:
        return f"🟡 {r['name']} (login info বাকি)"
    try:
        msg = _get_client(pid, url, pu, pp, proxy=_row_proxy(r), flavor=_row_flavor(r),
                          api_base=_row_api(r), api_token=_row_token(r)).check()
        n = msg.replace("OK,", "").strip()
        return f"🟢 {r['name']} — Login Success, {n}"
    except LoginError as e:
        return f"🔴 {r['name']} — login failed: {e}"
    except CooldownError:
        return f"🟡 {r['name']} — Login Success, report cooldown (15s por abar)"
    except Exception as e:
        err = str(e)
        if "403" in err:
            return f"🟡 {r['name']} — Login Success, kintu report blocked (403 Forbidden)"
        return f"🔴 {r['name']} — error: {err[:80]}"


def _panel_cdr(pid: int, fnum: str = "") -> str:
    con = db()
    r = con.execute("SELECT * FROM panels WHERE id=?", (pid,)).fetchone()
    con.close()
    if not r:
        return "❌ Panel পাওয়া যায়নি।"
    url = r["url"] if "url" in r.keys() else ""
    pu = r["puser"] if "puser" in r.keys() else ""
    pp = r["ppass"] if "ppass" in r.keys() else ""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        res = _get_client(pid, url, pu, pp, proxy=_row_proxy(r), flavor=_row_flavor(r),
                          api_base=_row_api(r), api_token=_row_token(r)).fetch_cdr(f"{today} 00:00:00", f"{today} 23:59:59", fnum=fnum, limit=200)
    except LoginError as e:
        return f"🔴 {r['name']} login failed: {e}"
    except CooldownError:
        return f"🟡 {r['name']} — panel 15s cooldown, ektu por abar try korun"
    except Exception as e:
        return f"🔴 {r['name']} error: {str(e)[:120]}"
    rows = res["rows"]
    if not rows:
        return f"📊 {r['name']} — আজ কোনো record নেই।"
    lines = [f"📊 {r['name']} — আজ {len(rows)} record(s):"]
    for cells in rows[:15]:
        # Date, Range, Number, CLI, Client, SMS, Currency, MyPayout, ClientPayout
        try:
            lines.append(f"{cells[0]} | {cells[2]} | CLI:{cells[3]} | {cells[5]} SMS | {cells[7]} {cells[6]}")
        except IndexError:
            lines.append(" | ".join(cells[:5]))
    if len(rows) > 15:
        lines.append(f"...আরো {len(rows) - 15} টা")
    if res["totals"]:
        lines.append("\nTotals: " + " | ".join(res["totals"]))
    return "\n".join(lines)


def _panel_csv(pid: int):
    con = db()
    r = con.execute("SELECT * FROM panels WHERE id=?", (pid,)).fetchone()
    con.close()
    if not r:
        raise LoginError("Panel পাওয়া যায়নি।")
    url = r["url"] if "url" in r.keys() else ""
    pu = r["puser"] if "puser" in r.keys() else ""
    pp = r["ppass"] if "ppass" in r.keys() else ""
    today = datetime.now().strftime("%Y-%m-%d")
    data = _get_client(pid, url, pu, pp, proxy=_row_proxy(r), flavor=_row_flavor(r),
                       api_base=_row_api(r), api_token=_row_token(r)).export_csv(f"{today} 00:00:00", f"{today} 23:59:59")
    return r["name"], today, data


async def cmd_panel_status(update, ctx):
    con = db()
    panels = con.execute("SELECT * FROM panels").fetchall()
    servers = con.execute("SELECT * FROM servers").fetchall()
    con.close()
    await update.message.reply_text("⏳ Live check চলছে...")
    lines = await asyncio.gather(
        *(asyncio.to_thread(_live_panel_check, p["id"]) for p in panels))
    msg = "📊 Panel Status (live login):\n\n"
    msg += "\n".join(lines) or "No panels.\n"
    msg += "\n\n💻 Servers:\n"
    msg += "\n".join(f"{'🟢' if s['status']=='ON' else '🔴'} {s['name']}" for s in servers) or "No servers."
    await update.message.reply_text(msg)

async def cmd_remove_panel_list(update, ctx):
    con = db()
    rows = con.execute("SELECT * FROM panels").fetchall()
    con.close()
    if not rows:
        await update.message.reply_text("কোনো panel নেই।")
        return
    kb = [[InlineKeyboardButton(f"❌ {r['name']}", callback_data=f"delpanel:{r['id']}")] for r in rows]
    await update.message.reply_text("Remove করতে click করুন:", reply_markup=InlineKeyboardMarkup(kb))

async def cmd_servers(update, ctx):
    con = db()
    rows = con.execute("SELECT * FROM servers ORDER BY id DESC").fetchall()
    con.close()
    kb = []
    for r in rows:
        kb.append([InlineKeyboardButton(f"❌ {r['name']}", callback_data=f"delserver:{r['id']}"),
                   InlineKeyboardButton(f"🔄 {r['status']}", callback_data=f"togserver:{r['id']}")])
    kb.append([InlineKeyboardButton("➕ Add Server", callback_data="server_add"),
               InlineKeyboardButton("➖ Remove Server", callback_data="server_remove")])
    txt = "💻 Servers:\n" + ("\n".join(f"• {r['name']} — {r['url'] or '-'} [{r['status']}]" for r in rows) if rows else "কোনো server নেই।")
    await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb))

async def cmd_stats(update, ctx):
    con = db()
    u = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    p = con.execute("SELECT COUNT(*) c FROM panels").fetchone()["c"]
    n = con.execute("SELECT COUNT(*) c FROM numbers").fetchone()["c"]
    s = con.execute("SELECT COUNT(*) c FROM servers").fetchone()["c"]
    pend = con.execute("SELECT COUNT(*) c FROM pending WHERE status='PENDING'").fetchone()["c"]
    bal = con.execute("SELECT COALESCE(SUM(balance),0) s FROM users").fetchone()["s"]
    con.close()
    await update.message.reply_text(
        f"📈 Stats:\n\n👥 Users: {u}\n📋 Panels: {p}\n📦 Numbers: {n}\n💻 Servers: {s}\n⏳ Pending: {pend}\n💰 Total balance: {bal}")

async def cmd_users(update, ctx, admin):
    con = db()
    rows = con.execute("SELECT * FROM users ORDER BY rowid DESC LIMIT 20").fetchall()
    con.close()
    if not rows:
        await update.message.reply_text("No users.")
        return
    msg = "👥 Last 20 Users:\n\n" + "\n".join(
        f"`{r['user_id']}` | @{r['username'] or '-'} | {r['first_name'] or ''} | Bal:{r['balance']} | {'🚫' if r['banned'] else '✅'}"
        for r in rows)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_country_list(update, ctx):
    con = db()
    rows = con.execute("SELECT * FROM country_emoji").fetchall()
    con.close()
    msg = "👀 Country Emoji:\n" + ("\n".join(f"{r['code']} = {r['emoji']}" for r in rows) if rows else "(খালি)")
    await update.message.reply_text(msg)

async def cmd_subadmins(update, ctx):
    if not can_manage_admins(update.effective_user.id):
        await update.message.reply_text("❌ Only main/master admin.")
        return
    con = db()
    rows = con.execute("SELECT * FROM sub_admins").fetchall()
    con.close()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Sub-Admin", callback_data="sub_add"),
         InlineKeyboardButton("➖ Remove Sub-Admin", callback_data="sub_remove")]
    ])
    msg = "🧑‍✈️ Sub Admins:\n" + ("\n".join(f"`{r['user_id']}`" for r in rows) if rows else "(খালি)")
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)


async def cmd_masterlist(update, ctx):
    if not is_main_admin(update.effective_user.id):
        await update.message.reply_text("❌ Only main admin.")
        return
    con = db()
    rows = con.execute("SELECT * FROM master_admins").fetchall()
    con.close()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Master", callback_data="master_add"),
         InlineKeyboardButton("➖ Remove Master", callback_data="master_remove")]
    ])
    msg = "👑 Master Admin List:\n" + ("\n".join(f"`{r['user_id']}`" for r in rows) if rows else "(খালি)")
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)


async def cmd_config(update, ctx):
    import config as _cfg
    msg = ("⚙️ Config Setup\n\n"
           f"⏱️ Poll Seconds: {get_setting('poll_seconds', str(_cfg.POLL_SECONDS))}\n"
           f"🎁 Referral Reward: {get_setting('ref_reward', str(_cfg.REF_REWARD))}\n"
           f"💸 Min Withdraw: {get_setting('min_withdraw', str(_cfg.MIN_WITHDRAW))}\n"
           f"🔢 Numbers/Request: {get_setting('numbers_per_request', '1')}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ Poll Seconds", callback_data="cfg_poll"),
         InlineKeyboardButton("🎁 Ref Reward", callback_data="cfg_ref")],
        [InlineKeyboardButton("💸 Min Withdraw", callback_data="cfg_min"),
         InlineKeyboardButton("🔢 Numbers/Req", callback_data="cfg_npr")],
    ])
    await update.message.reply_text(msg, reply_markup=kb)


async def cmd_apipanels(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    con = db()
    try:
        rows = con.execute("SELECT * FROM panels WHERE flavor='v3' OR api_base!=''").fetchall()
    except Exception:
        rows = []
    con.close()
    kb = [[InlineKeyboardButton("➕ Add API Panel", callback_data="api_add")]]
    if not rows:
        await update.message.reply_text("🔌 API panel nai। Add API Panel diye jog korun:",
                                        reply_markup=InlineKeyboardMarkup(kb))
        return
    await update.message.reply_text(f"🔌 API Panels ({len(rows)}):",
                                    reply_markup=InlineKeyboardMarkup(kb))
    for r in rows:
        try:
            api = r["api_base"] or ""
        except Exception:
            api = ""
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Test API", callback_data=f"apitest:{r['id']}"),
             InlineKeyboardButton("📊 CDR", callback_data=f"panelstats:{r['id']}")],
        ])
        await update.message.reply_text(
            f"🔌 {r['name']}\n🌐 {api or '-'}", reply_markup=kb)


async def cmd_adminpanel(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit_msg=None):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistics", callback_data="ap_stats")],
        [InlineKeyboardButton("👥 Users", callback_data="ap_users")],
        [InlineKeyboardButton("📱 Stock", callback_data="ap_stock")],
        [InlineKeyboardButton("➕ Add Numbers", callback_data="ap_addnum")],
        [InlineKeyboardButton("➖ Remove Numbers", callback_data="ap_rmnum")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="ap_broadcast")],
        [InlineKeyboardButton("[BS ADMIN]", callback_data="ap_bsadmin")],
        [InlineKeyboardButton("💾 Backup", callback_data="ap_backup")],
        [InlineKeyboardButton("⬅️ Back", callback_data="ap_back")],
    ])
    if edit_msg is not None:
        await edit_msg.edit_text("👑 Admin Panel", reply_markup=kb)
    else:
        await update.message.reply_text("👑 Admin Panel", reply_markup=kb)


async def cmd_checker_status(update, ctx):
    con = db()
    pend_o = con.execute("SELECT COUNT(*) c FROM orders WHERE status='pending'").fetchone()["c"]
    done_o = con.execute("SELECT COUNT(*) c FROM orders WHERE status='completed'").fetchone()["c"]
    panels = con.execute("SELECT COUNT(*) c FROM panels WHERE status='ON'").fetchone()["c"]
    groups = con.execute("SELECT COUNT(*) c FROM otp_groups").fetchone()["c"]
    con.close()
    await update.message.reply_text(
        "📊 Checker Status\n\n"
        f"Mode: {get_setting('checker_mode', 'ON')}\n"
        f"Panels ON: {panels}\n"
        f"⏳ Pending orders: {pend_o}\n"
        f"✅ Completed: {done_o}\n"
        f"📨 OTP groups: {groups}\n"
        f"🕒 Last poll: {_last_poll}\n"
        f"📄 OTP Format: {get_setting('otp_format', 'v0.2')} | "
        f"👁️ {get_setting('otp_visibility', 'show')} | "
        f"📏 Prefix: {get_setting('prefix_length', '7')} ({get_setting('prefix_display', 'ON')})")

async def cmd_pending(update, ctx, admin):
    con = db()
    rows = con.execute("SELECT * FROM pending WHERE status='PENDING' ORDER BY id DESC LIMIT 20").fetchall()
    con.close()
    if not rows:
        await update.message.reply_text("⏳ No pending.")
        return
    if not admin:
        # normal user: only own
        con = db()
        rows = con.execute("SELECT * FROM pending WHERE user_id=? ORDER BY id DESC LIMIT 10", (update.effective_user.id,)).fetchall()
        con.close()
        if not rows:
            await update.message.reply_text("⏳ Your pending: none.")
            return
        await update.message.reply_text("⏳ Your Pending:\n" + "\n".join(f"#{r['id']} {r['type']}: {r['details']} [{r['status']}]" for r in rows))
        return
    for r in rows:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"pend_ok:{r['id']}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"pend_no:{r['id']}")]])
        await update.message.reply_text(
            f"⏳ #{r['id']} | User `{r['user_id']}`\nType: {r['type']}\n{r['details']}",
            parse_mode="Markdown", reply_markup=kb)

async def cmd_my_history(update, ctx):
    con = db()
    rows = con.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 15", (update.effective_user.id,)).fetchall()
    con.close()
    if not rows:
        await update.message.reply_text("No history.")
    else:
        await update.message.reply_text("📜 My History:\n\n" + "\n".join(f"{r['created_at']} | {r['amount']} | {r['reason']}" for r in rows))

def get_otp_groups() -> list:
    """DB groups, empty hole config default."""
    con = db()
    rows = con.execute("SELECT chat_id, title FROM otp_groups").fetchall()
    con.close()
    if rows:
        return [(r["chat_id"], r["title"] or "") for r in rows]
    try:
        from config import OTP_GROUP
    except Exception:
        OTP_GROUP = ""
    return [(OTP_GROUP, "")] if OTP_GROUP else []


async def cmd_otpgroups(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    groups = get_otp_groups()
    kb = [[InlineKeyboardButton("➕ Add OTP Group", callback_data="otpg_add")]]
    for cid, title in groups:
        kb.append([InlineKeyboardButton(f"❌ {title or cid}", callback_data=f"otpg_del:{cid}")])
    msg = "📨 OTP Groups (sob panel er OTP ekhane jabe):\n\n"
    msg += "\n".join(f"• {t or c}  (`{c}`)" for c, t in groups) or "(খালি)"
    msg += "\n\nAdd: group er @username (যেমন @bssyrxteamotp) বা ID (-100...) পাঠান।"
    await update.message.reply_text(msg, parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(kb))


# ---------- Number stock / orders (number-bot features) ----------
_pending_dms: list = []  # (user_id, text) filled by poller
_last_poll: str = "-"


def svc_label(svc: str) -> str:
    for s, label in get_services():
        if s == svc:
            return label
    return svc


def country_of_number(number: str) -> str:
    from country import COUNTRIES
    d = "".join(ch for ch in (number or "") if ch.isdigit())
    for length in (4, 3, 2, 1):
        if COUNTRIES.get(d[:length]):
            return COUNTRIES[d[:length]][0]
    return ""


def stock_count(svc: str) -> int:
    con = db()
    n = con.execute("SELECT COUNT(*) c FROM stock WHERE service=?", (svc,)).fetchone()["c"]
    con.close()
    return n


def stock_countries(svc: str) -> list:
    con = db()
    rows = con.execute("SELECT country, COUNT(*) c FROM stock WHERE service=? GROUP BY country ORDER BY c DESC",
                       (svc,)).fetchall()
    con.close()
    return [(r["country"] or "??", r["c"]) for r in rows]


def take_stock_number(svc: str, country: str = ""):
    con = db()
    if country:
        r = con.execute("SELECT id, number FROM stock WHERE service=? AND country=? LIMIT 1",
                        (svc, country)).fetchone()
    else:
        r = con.execute("SELECT id, number FROM stock WHERE service=? LIMIT 1", (svc,)).fetchone()
    if r:
        con.execute("DELETE FROM stock WHERE id=?", (r["id"],))
        con.commit()
    con.close()
    return r["number"] if r else None


def restock_number(svc: str, number: str):
    con = db()
    try:
        con.execute("INSERT OR IGNORE INTO stock(service,number,country,created_at) VALUES(?,?,?,?)",
                    (svc, number, country_of_number(number), now()))
        con.commit()
    except Exception:
        pass
    con.close()


def active_order(uid: int):
    con = db()
    r = con.execute("SELECT * FROM orders WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
                    (uid,)).fetchone()
    con.close()
    return r


def order_buttons(oid: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh OTP", callback_data=f"nb_refresh:{oid}")],
        [InlineKeyboardButton("🔁 Change Number", callback_data=f"nb_change:{oid}")],
    ])


async def cmd_numbers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    con = db()
    rows = con.execute("SELECT * FROM orders WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 5",
                       (uid,)).fetchall()
    con.close()
    if rows:
        from country import iso_info as _iso3
        o0 = rows[0]
        flag, cname = _iso3(o0["country"])
        kb = []
        for o in rows:
            kb.append([InlineKeyboardButton(f"📋 {o['number']}",
                                           copy_text=CopyTextButton(o["number"]))])
        kb.append([InlineKeyboardButton("🔄 Refresh OTP", callback_data="nb_refresh_all")])
        kb.append([InlineKeyboardButton("🔁 Change Number", callback_data=f"nb_change:{o0['id']}")])
        kb.append([InlineKeyboardButton("⬅️ Main Menu", callback_data="nb_menu")])
        await update.message.reply_text(
            "📱 Number Assigned Successfully\n"
            "➖➖➖➖➖➖➖➖➖➖\n"
            f"📲 Service : {o0['service'].capitalize()}\n"
            f"🌍 Country : {flag} {cname}\n\n"
            "⏳ Waiting for OTP",
            reply_markup=InlineKeyboardMarkup(kb))
        return
    kb = []
    for svc, label in get_services():
        kb.append([InlineKeyboardButton(f"{label} ({stock_count(svc)})",
                                       callback_data=f"nb_svc:{svc}")])
    await update.message.reply_text("📱 Service select korun:",
                                    reply_markup=InlineKeyboardMarkup(kb))


async def send_order_card(sender, o):
    """sender: async callable like message.reply_text / query.message.reply_text"""
    from country import iso_info
    flag, cname = iso_info(o["country"])
    otp_line = f"\n🔐 OTP: `{o['otp']}`" if o["otp"] else "\n⏳ Waiting for OTP"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📋 {o['number']}", copy_text=CopyTextButton(o["number"]))],
        [InlineKeyboardButton("🔄 Refresh OTP", callback_data=f"nb_refresh:{o['id']}")],
        [InlineKeyboardButton("🔁 Change Number", callback_data=f"nb_change:{o['id']}")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="nb_menu")],
    ])
    await sender(
        "📱 Number Assigned Successfully\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        f"📲 Service : {o['service'].capitalize()}\n"
        f"🌍 Country : {flag} {cname}\n"
        f"{otp_line}",
        parse_mode="Markdown", reply_markup=kb)


async def cmd_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    con = db()
    r = con.execute("SELECT * FROM users WHERE user_id=?", (u.id,)).fetchone()
    ords = con.execute("SELECT COUNT(*) c FROM orders WHERE user_id=?", (u.id,)).fetchone()["c"]
    refs = con.execute("SELECT COUNT(*) c FROM referrals WHERE referrer_id=?", (u.id,)).fetchone()["c"]
    con.close()
    bal = r["balance"] if r else 0
    joined = r["created_at"] if r and "created_at" in r.keys() else "-"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💸 Withdraw", callback_data="prof_wd")]])
    await update.message.reply_text(
        f"👤 Profile\n\n🆔 `{u.id}`\n👤 @{u.username or '-'}\n"
        f"💰 Balance: {bal}\n📦 Orders: {ords}\n🎁 Referrals: {refs}\n📅 Joined: {joined}",
        parse_mode="Markdown", reply_markup=kb)


async def cmd_referral(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    try:
        me = await ctx.bot.get_me()
        link = f"https://t.me/{me.username}?start={u.id}"
    except Exception:
        link = f"?start={u.id}"
    con = db()
    n = con.execute("SELECT COUNT(*) c FROM referrals WHERE referrer_id=?", (u.id,)).fetchone()["c"]
    con.close()
    import config as _cfg5
    try:
        _rw2 = float(get_setting("ref_reward", str(_cfg5.REF_REWARD)))
    except ValueError:
        _rw2 = 5
    await update.message.reply_text(
        f"🎁 Referral\n\nLink: `{link}`\n👥 Invited: {n}\n💰 Per invite: {_rw2}",
        parse_mode="Markdown")


TEMPMAIL_API = "https://www.1secmail.com/api/v1/"


def _tm_get(params: dict):
    import requests as _rq
    r = _rq.get(TEMPMAIL_API, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def tm_domains():
    try:
        return _tm_get({"action": "getDomainList"})
    except Exception:
        return ["1secmail.com"]


def tm_new_address(uid: int):
    import random as _rnd
    import string as _st
    domains = tm_domains()
    login = "".join(_rnd.choice(_st.ascii_lowercase + _st.digits) for _ in range(12))
    domain = domains[0]
    con = db()
    con.execute("INSERT OR REPLACE INTO tempmails(telegram_id,login,domain) VALUES(?,?,?)",
                (uid, login, domain))
    con.commit(); con.close()
    return login, domain


def tm_inbox(login: str, domain: str):
    try:
        return _tm_get({"action": "getMessages", "login": login, "domain": domain}) or []
    except Exception:
        return []


def tm_read(login: str, domain: str, mid: int):
    d = _tm_get({"action": "readMessage", "login": login, "domain": domain, "id": mid})
    body = d.get("textBody") or d.get("body") or ""
    import re as _re
    body = _re.sub(r"<[^>]+>", " ", body)
    return d.get("subject", ""), d.get("from", ""), " ".join(body.split())[:1500]


async def cmd_tempmail(update: Update, ctx: ContextTypes.DEFAULT_TYPE, login="", domain=""):
    uid = update.effective_user.id
    if not login:
        con = db()
        r = con.execute("SELECT login, domain FROM tempmails WHERE telegram_id=?", (uid,)).fetchone()
        con.close()
        if r:
            login, domain = r["login"], r["domain"]
        else:
            await update.message.reply_text("⏳ Email বানাচ্ছি...")
            try:
                login, domain = await asyncio.to_thread(tm_new_address, uid)
            except Exception as e:
                await update.message.reply_text(f"❌ TempMail error: {str(e)[:100]}")
                return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Inbox", callback_data="tm_inbox"),
         InlineKeyboardButton("🆕 New Email", callback_data="tm_new")],
    ])
    await update.message.reply_text(f"📧 Temp Mail\n\n`{login}@{domain}`",
                                    parse_mode="Markdown", reply_markup=kb)


async def cmd_traffic(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from datetime import date as _date
    today = _date.today().strftime("%Y-%m-%d")
    con = db()
    total = con.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
    tday = con.execute("SELECT COUNT(*) c FROM orders WHERE substr(created_at,1,10)=?", (today,)).fetchone()["c"]
    top_cty = con.execute("SELECT country, COUNT(*) c FROM orders GROUP BY country ORDER BY c DESC LIMIT 5").fetchall()
    top_svc = con.execute("SELECT service, COUNT(*) c FROM orders GROUP BY service ORDER BY c DESC LIMIT 5").fetchall()
    con.close()
    msg = f"📈 Live Traffic\n\n📦 Total orders: {total}\n📦 Today: {tday}\n\nTop Country:\n"
    msg += "\n".join(f"• {r['country'] or '??'}: {r['c']}" for r in top_cty) or "-\n"
    msg += "\n\nTop Service:\n"
    msg += "\n".join(f"• {svc_label(r['service'])}: {r['c']}" for r in top_svc) or "-"
    await update.message.reply_text(msg)


async def cmd_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = [f"• {label}: {stock_count(svc)}" for svc, label in get_services()]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Stock", callback_data="stock_add"),
         InlineKeyboardButton("➖ Remove Stock", callback_data="stock_rm")],
    ])
    await update.message.reply_text("📱 Number Stock:\n\n" + "\n".join(lines),
                                    reply_markup=kb)


async def cmd_withdrawals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    con = db()
    rows = con.execute("SELECT * FROM withdrawals WHERE status='pending' ORDER BY id DESC LIMIT 15").fetchall()
    con.close()
    if not rows:
        await update.message.reply_text("💸 No pending withdrawals.")
        return
    for r in rows:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"wd_ok:{r['id']}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"wd_no:{r['id']}")]])
        await update.message.reply_text(
            f"💸 #{r['id']} | User `{r['user_id']}`\n💰 {r['amount']}\n📮 `{r['address']}`",
            parse_mode="Markdown", reply_markup=kb)


# ---------- callbacks ----------
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = update.effective_user.id

    # user can get panel login (no admin needed)
    if data.startswith("getlogin:"):
        pid = int(data.split(":")[1])
        con0 = db()
        r = con0.execute("SELECT * FROM panels WHERE id=?", (pid,)).fetchone()
        con0.close()
        if not r:
            await q.message.reply_text("❌ Panel পাওয়া যায়নি।")
            return
        if r["status"] != "ON":
            await q.message.reply_text("🔴 Panel OFF আছে।")
            return
        try: url = r["url"]
        except Exception: url = ""
        try: pu = r["puser"]
        except Exception: pu = ""
        try: pp = r["ppass"]
        except Exception: pp = ""
        await q.message.reply_text(
            f"🔑 {r['name']}\n\n🔗 URL: {url or '-'}\n👤 User: {pu or '-'}\n🔑 Password: {pp or '-'}\n\n👉 URL এ ঢুকে User + Password বসিয়ে Login করুন।")
        return

    # CDR + CSV: everyone (banned already blocked in on_text; callbacks check here)
    if data.startswith("panelstats:"):
        if is_banned(uid):
            await q.message.reply_text("⛔ You are banned.")
            return
        pid = int(data.split(":")[1])
        await q.message.reply_text("⏳ Panel এ login করে CDR আনছি...")
        txt = await asyncio.to_thread(_panel_cdr, pid)
        await q.message.reply_text(txt[:4000])
        return
    if data.startswith("panelcsv:"):
        if not is_admin(uid):
            return
        pid = int(data.split(":")[1])
        await q.message.reply_text("⏳ CSV export হচ্ছে...")
        try:
            name, today, content = await asyncio.to_thread(_panel_csv, pid)
            await q.message.reply_document(document=content, filename=f"{name}_{today}.csv")
        except LoginError as e:
            await q.message.reply_text(f"🔴 Export failed: {e}")
        except Exception as e:
            await q.message.reply_text(f"🔴 Export error: {str(e)[:150]}")
        return

    # ----- number-bot user callbacks (no admin needed) -----
    if data.startswith("nb_svc:"):
        svc = data.split(":", 1)[1]
        kb = []
        from country import iso_info as _iso
        for code, n in stock_countries(svc):
            _flag, _name = _iso(code)
            kb.append([InlineKeyboardButton(f"{_flag} {_name} ({n})",
                                           callback_data=f"nb_cty:{svc}:{code}")])
        if not kb:
            await q.message.reply_text(f"{svc_label(svc)} — stock খালি।")
            return
        await q.message.reply_text(f"{svc_label(svc)} — country select:",
                                   reply_markup=InlineKeyboardMarkup(kb))
        return
    if data.startswith("nb_cty:"):
        _, svc, code = data.split(":", 2)
        if active_order(uid):
            await q.message.reply_text("❌ আপনার active number আছে। age oita ses করুন।")
            return
        try:
            want = max(1, min(20, int(get_setting("numbers_per_request", "1"))))
        except ValueError:
            want = 1
        got = []
        for _ in range(want):
            num = take_stock_number(svc, "" if code == "??" else code)
            if not num:
                num = take_stock_number(svc, "")
            if not num:
                break
            got.append(num)
        if not got:
            await q.message.reply_text("❌ Stock ses।")
            return
        from country import iso_info
        flag, cname = iso_info(code)
        con0 = db()
        oids = []
        for num in got:
            cur = con0.execute("INSERT INTO orders(user_id,number,service,country,created_at) VALUES(?,?,?,?,?)",
                               (uid, num, svc, code, now()))
            oids.append((cur.lastrowid, num))
        con0.commit(); con0.close()
        kb = []
        for _oid, n in oids:
            kb.append([InlineKeyboardButton(f"📋 {n}", copy_text=CopyTextButton(n))])
        kb.append([InlineKeyboardButton("🔄 Refresh OTP", callback_data="nb_refresh_all")])
        kb.append([InlineKeyboardButton("🔁 Change Number", callback_data=f"nb_change:{oids[0][0]}")])
        kb.append([InlineKeyboardButton("⬅️ Main Menu", callback_data="nb_menu")])
        await q.message.reply_text(
            "📱 Number Assigned Successfully\n"
            "➖➖➖➖➖➖➖➖➖➖\n"
            f"📲 Service : {svc.capitalize()}\n"
            f"🌍 Country : {flag} {cname}\n\n"
            "⏳ Waiting for OTP",
            reply_markup=InlineKeyboardMarkup(kb))
        return
    if data == "nb_refresh_all":
        con0 = db()
        rows = con0.execute("SELECT * FROM orders WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 5",
                            (uid,)).fetchall()
        con0.close()
        if not rows:
            await q.message.reply_text("❌ Active number nai।")
            return
        lines = []
        for o in rows:
            otp_t = f"`{o['otp']}`" if o["otp"] else "⏳ wait"
            lines.append(f"`{o['number']}` → {otp_t}")
        await q.message.reply_text("🔄 OTP Status:\n\n" + "\n".join(lines), parse_mode="Markdown")
        return
    if data == "nb_menu":
        if is_admin(uid):
            await q.message.reply_text("Main Menu", reply_markup=admin_menu())
        else:
            await q.message.reply_text("Main Menu", reply_markup=user_menu())
        return
    if data.startswith("nb_refresh:"):
        oid = int(data.split(":")[1])
        con0 = db()
        o = con0.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (oid, uid)).fetchone()
        con0.close()
        if not o:
            return
        if o["otp"]:
            await q.message.reply_text(f"🔐 OTP: `{o['otp']}`\n📱 `{o['number']}` ({o['service']})",
                                       parse_mode="Markdown")
        else:
            await q.message.reply_text("⏳ OTP এখনো আসেনি। ektu por Refresh din.")
        return
    if data.startswith("nb_change:"):
        oid = int(data.split(":")[1])
        con0 = db()
        o = con0.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (oid, uid)).fetchone()
        con0.close()
        if not o or o["status"] != "pending":
            await q.message.reply_text("❌ Change kora jabe na।")
            return
        restock_number(o["service"], o["number"])
        try:
            want = max(1, min(20, int(get_setting("numbers_per_request", "1"))))
        except ValueError:
            want = 1
        got = []
        for _ in range(want):
            num = take_stock_number(o["service"], o["country"]) or take_stock_number(o["service"], "")
            if not num:
                break
            got.append(num)
        con0 = db()
        if not got:
            con0.execute("UPDATE orders SET status='changed' WHERE id=?", (oid,))
            con0.commit(); con0.close()
            await q.message.reply_text("❌ Notun stock nai।")
            return
        from country import iso_info as _iso2
        flag, cname = _iso2(o["country"])
        con0.execute("UPDATE orders SET status='changed' WHERE user_id=? AND status='pending'", (uid,))
        oids = []
        for num in got:
            cur = con0.execute("INSERT INTO orders(user_id,number,service,country,created_at) VALUES(?,?,?,?,?)",
                               (uid, num, o["service"], o["country"], now()))
            oids.append((cur.lastrowid, num))
        con0.commit(); con0.close()
        kb = []
        for _oid, n in oids:
            kb.append([InlineKeyboardButton(f"📋 {n}", copy_text=CopyTextButton(n))])
        kb.append([InlineKeyboardButton("🔄 Refresh OTP", callback_data="nb_refresh_all")])
        kb.append([InlineKeyboardButton("🔁 Change Number", callback_data=f"nb_change:{oids[0][0]}")])
        kb.append([InlineKeyboardButton("⬅️ Main Menu", callback_data="nb_menu")])
        await q.message.reply_text(
            "📱 Number Assigned Successfully\n"
            "➖➖➖➖➖➖➖➖➖➖\n"
            f"📲 Service : {o['service'].capitalize()}\n"
            f"🌍 Country : {flag} {cname}\n\n"
            "⏳ Waiting for OTP",
            reply_markup=InlineKeyboardMarkup(kb))
        return
    if data == "prof_wd":
        ctx.user_data["state"] = "wd_amt"
        import config as _cfg4
        try:
            _minwd2 = float(get_setting("min_withdraw", str(_cfg4.MIN_WITHDRAW)))
        except ValueError:
            _minwd2 = 10
        await q.message.reply_text(f"Withdraw amount পাঠান (min {_minwd2}, balance: {get_balance(uid)}):",
                                   reply_markup=cancel_menu())
        return
    if data == "tm_new":
        await q.message.reply_text("⏳ Email বানাচ্ছি...")
        try:
            login, domain = await asyncio.to_thread(tm_new_address, uid)
        except Exception as e:
            await q.message.reply_text(f"❌ TempMail error: {str(e)[:100]}")
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Inbox", callback_data="tm_inbox"),
             InlineKeyboardButton("🆕 New Email", callback_data="tm_new")]])
        await q.message.reply_text(f"📧 Temp Mail\n\n`{login}@{domain}`",
                                   parse_mode="Markdown", reply_markup=kb)
        return
    if data == "tm_inbox":
        con0 = db()
        r = con0.execute("SELECT login, domain FROM tempmails WHERE telegram_id=?", (uid,)).fetchone()
        con0.close()
        if not r:
            await q.message.reply_text("❌ Email nai।")
            return
        try:
            msgs = await asyncio.to_thread(tm_inbox, r["login"], r["domain"])
        except Exception as e:
            await q.message.reply_text(f"❌ Inbox error: {str(e)[:100]}")
            return
        if not msgs:
            await q.message.reply_text("📥 Inbox খালি।")
            return
        kb = [[InlineKeyboardButton(f"✉️ {m.get('subject','')[:30]}", callback_data=f"tm_read:{m['id']}")]
              for m in msgs[:10]]
        await q.message.reply_text("📥 Inbox:", reply_markup=InlineKeyboardMarkup(kb))
        return
    if data.startswith("tm_read:"):
        mid = int(data.split(":")[1])
        con0 = db()
        r = con0.execute("SELECT login, domain FROM tempmails WHERE telegram_id=?", (uid,)).fetchone()
        con0.close()
        if not r:
            return
        try:
            subj, frm, body = await asyncio.to_thread(tm_read, r["login"], r["domain"], mid)
        except Exception as e:
            await q.message.reply_text(f"❌ Read error: {str(e)[:100]}")
            return
        otp = extract_otp(f"{subj} {body}")
        await q.message.reply_text(f"✉️ {subj}\n👤 {frm}\n🔐 OTP: {otp or '-'}\n\n{body[:1500]}")
        return

    if not is_admin(uid):
        return

    con = db()
    if data.startswith("delpanel:"):
        pid = int(data.split(":")[1])
        con.execute("DELETE FROM numbers WHERE panel_id=?", (pid,))
        con.execute("DELETE FROM panels WHERE id=?", (pid,))
        con.commit()
        await q.edit_message_text("✅ Panel deleted.")
    elif data.startswith("togpanel:"):
        pid = int(data.split(":")[1])
        r = con.execute("SELECT status FROM panels WHERE id=?", (pid,)).fetchone()
        ns = "OFF" if r and r["status"] == "ON" else "ON"
        con.execute("UPDATE panels SET status=? WHERE id=?", (ns, pid))
        con.commit()
        await q.edit_message_text(f"Panel → {ns}")
    elif data.startswith("delserver:"):
        sid = int(data.split(":")[1])
        con.execute("DELETE FROM servers WHERE id=?", (sid,))
        con.commit()
        await q.edit_message_text("✅ Server deleted.")
    elif data.startswith("togserver:"):
        sid = int(data.split(":")[1])
        r = con.execute("SELECT status FROM servers WHERE id=?", (sid,)).fetchone()
        ns = "OFF" if r and r["status"] == "ON" else "ON"
        con.execute("UPDATE servers SET status=? WHERE id=?", (ns, sid))
        con.commit()
        await q.edit_message_text(f"Server → {ns}")
    elif data.startswith("pend_ok:") or data.startswith("pend_no:"):
        pid = int(data.split(":")[1])
        ns = "APPROVED" if data.startswith("pend_ok") else "DECLINED"
        con.execute("UPDATE pending SET status=? WHERE id=?", (ns, pid))
        con.commit()
        await q.edit_message_text(f"Pending #{pid} → {ns}")
    elif data == "server_add":
        ctx.user_data["state"] = "server_add"
        await q.message.reply_text("নতুন server: `Name=URL`", parse_mode="Markdown", reply_markup=cancel_menu())
    elif data == "server_remove":
        ctx.user_data["state"] = "server_remove"
        await q.message.reply_text("Remove করতে server name পাঠান:", reply_markup=cancel_menu())
    elif data == "sub_add":
        ctx.user_data["state"] = "subadmin_add"
        await q.message.reply_text("Sub-admin ID বা @username পাঠান:", reply_markup=cancel_menu())
    elif data == "sub_remove":
        ctx.user_data["state"] = "subadmin_remove"
        await q.message.reply_text("Remove করতে ID বা @username পাঠান:", reply_markup=cancel_menu())
    elif data == "stock_add":
        ctx.user_data["state"] = "stock_add_svc"
        await q.message.reply_text("Service name পাঠান: telegram / whatsapp / facebook / instagram",
                                   reply_markup=cancel_menu())
    elif data == "stock_rm":
        kb = [[InlineKeyboardButton(label, callback_data=f"stock_rm_svc:{svc}")]
              for svc, label in get_services()]
        await q.message.reply_text("Remove — service select:",
                                   reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("stock_rm_svc:"):
        svc = data.split(":", 1)[1]
        kb = []
        for code, n in stock_countries(svc):
            kb.append([InlineKeyboardButton(f"{code} ({n}) — all",
                                           callback_data=f"stock_rm_all:{svc}:{code}"),
                       InlineKeyboardButton("list",
                                           callback_data=f"stock_rm_cty:{svc}:{code}")])
        await q.message.reply_text(f"{svc_label(svc)} — country:",
                                   reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    elif data.startswith("stock_rm_cty:"):
        _, svc, code = data.split(":", 2)
        con3 = db()
        rows = con3.execute("SELECT id, number FROM stock WHERE service=? AND country=? LIMIT 20",
                            (svc, code)).fetchall()
        con3.close()
        kb = [[InlineKeyboardButton(f"❌ {r['number']}", callback_data=f"stock_rm_one:{r['id']}")]
              for r in rows]
        await q.message.reply_text(f"{code} numbers (20):",
                                   reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    elif data.startswith("stock_rm_all:"):
        _, svc, code = data.split(":", 2)
        con3 = db()
        con3.execute("DELETE FROM stock WHERE service=? AND country=?", (svc, code))
        n = con3.execute("SELECT changes()").fetchone()[0]
        con3.commit(); con3.close()
        await q.edit_message_text(f"✅ Deleted {n} ({svc}/{code})")
    elif data.startswith("stock_rm_one:"):
        sid = int(data.split(":")[1])
        con3 = db()
        con3.execute("DELETE FROM stock WHERE id=?", (sid,))
        con3.commit(); con3.close()
        await q.edit_message_text("✅ Deleted.")
    elif data.startswith("wd_ok:") or data.startswith("wd_no:"):
        wid = int(data.split(":")[1])
        ok = data.startswith("wd_ok")
        con3 = db()
        w = con3.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
        if w and w["status"] == "pending":
            if ok:
                con3.execute("UPDATE withdrawals SET status='done' WHERE id=?", (wid,))
            else:
                con3.execute("UPDATE withdrawals SET status='declined' WHERE id=?", (wid,))
                con3.execute("UPDATE users SET balance=balance+? WHERE user_id=?",
                             (w["amount"], w["user_id"]))
                con3.execute("INSERT INTO transactions(user_id,amount,type,reason,admin_id,created_at) VALUES(?,?,?,?,?,?)",
                             (w["user_id"], w["amount"], "ADD", "withdraw refund", uid, now()))
            con3.commit()
        con3.close()
        await q.edit_message_text(f"Withdrawal #{wid} → {'✅ Approved' if ok else '❌ Declined+Refunded'}")
    elif data.startswith("cfg_"):
        key = {"cfg_poll": "poll_seconds", "cfg_ref": "ref_reward",
               "cfg_min": "min_withdraw", "cfg_npr": "numbers_per_request"}.get(data, "")
        if not key:
            return
        ctx.user_data["state"] = "cfg_value"
        ctx.user_data["cfg_key"] = key
        await q.message.reply_text(f"{key} এখন {get_setting(key, '-')} — notun value পাঠান:",
                                   reply_markup=cancel_menu())
    elif data.startswith("svc_del:"):
        code = data.split(":", 1)[1]
        con3 = db()
        con3.execute("DELETE FROM services WHERE code=?", (code,))
        con3.commit(); con3.close()
        await q.edit_message_text(f"✅ Service deleted: {code}")
    elif data.startswith("apitest:"):
        pid = int(data.split(":")[1])
        await q.message.reply_text("⏳ API test হচ্ছে...")
        try:
            line = await asyncio.to_thread(_live_panel_check, pid)
            await q.message.reply_text(f"🔌 API Test:\n{line}")
        except Exception as e:
            await q.message.reply_text(f"🔌 API Test fail: {str(e)[:150]}")
    elif data == "api_add":
        ctx.user_data["state"] = "api_add_base"
        await q.message.reply_text("API base URL পাঠান (যেমন `https://api.unixsms.com/api/v1`):",
                                   parse_mode="Markdown", reply_markup=cancel_menu())
    elif data == "master_add":
        if not is_main_admin(uid):
            return
        ctx.user_data["state"] = "master_add"
        await q.message.reply_text("Master Admin ID বা @username পাঠান:", reply_markup=cancel_menu())
    elif data == "master_remove":
        if not is_main_admin(uid):
            return
        ctx.user_data["state"] = "master_remove"
        await q.message.reply_text("Remove করতে ID বা @username পাঠান:", reply_markup=cancel_menu())
    elif data and data.startswith("ap_"):
        if not is_admin(uid):
            return
        if data == "ap_stats":
            con3 = db()
            u = con3.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            p = con3.execute("SELECT COUNT(*) c FROM panels").fetchone()["c"]
            n = con3.execute("SELECT COUNT(*) c FROM stock").fetchone()["c"]
            o = con3.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
            con3.close()
            await q.message.reply_text(f"📊 Statistics\n\n👥 Users: {u}\n📋 Panels: {p}\n📱 Stock: {n}\n📦 Orders: {o}")
        elif data == "ap_users":
            con3 = db()
            rows = con3.execute("SELECT user_id, username, balance FROM users ORDER BY rowid DESC LIMIT 20").fetchall()
            con3.close()
            msg = "👥 Users:\n" + ("\n".join(f"`{r['user_id']}` @{r['username'] or '-'} | {r['balance']}" for r in rows) if rows else "-")
            await q.message.reply_text(msg, parse_mode="Markdown")
        elif data == "ap_stock":
            lines = [f"• {label}: {stock_count(svc)}" for svc, label in get_services()]
            await q.message.reply_text("📱 Stock:\n\n" + "\n".join(lines))
        elif data == "ap_addnum":
            ctx.user_data["state"] = "stock_add_svc"
            await q.message.reply_text("Service name পাঠান: telegram / whatsapp / facebook / instagram",
                                       reply_markup=cancel_menu())
        elif data == "ap_rmnum":
            kb = [[InlineKeyboardButton(label, callback_data=f"stock_rm_svc:{svc}")]
                  for svc, label in get_services()]
            await q.message.reply_text("Remove — service select:",
                                       reply_markup=InlineKeyboardMarkup(kb))
        elif data == "ap_broadcast":
            ctx.user_data["state"] = "broadcast"
            await q.message.reply_text("Broadcast message পাঠান:", reply_markup=cancel_menu())
        elif data == "ap_bsadmin":
            if not is_main_admin(uid):
                await q.message.reply_text("❌ Only main admin.")
                return
            con3 = db()
            try:
                rows = con3.execute("SELECT user_id FROM master_admins").fetchall()
            except Exception:
                rows = []
            con3.close()
            await q.message.reply_text("[BS ADMIN]\n\nMaster Admins:\n" +
                                       ("\n".join(f"`{r['user_id']}`" for r in rows) if rows else "(খালি)"),
                                       parse_mode="Markdown")
        elif data == "ap_backup":
            if not is_main_admin(uid):
                await q.message.reply_text("❌ Only main admin.")
                return
            try:
                with open(DB, "rb") as f:
                    await q.message.reply_document(document=f, filename="bot_backup.db",
                                                   caption="💾 Backup")
            except Exception as e:
                await q.message.reply_text(f"❌ Backup fail: {str(e)[:100]}")
        elif data == "ap_back":
            await q.message.reply_text("📞 Main Menu", reply_markup=admin_menu())
    elif data == "otpg_add":
        ctx.user_data["state"] = "otpgroup_add"
        await q.message.reply_text("OTP group er @username বা ID পাঠান (bot group e admin থাকতে হবে):",
                                   reply_markup=cancel_menu())
    elif data.startswith("otpg_del:"):
        cid = data.split(":", 1)[1]
        con2 = db()
        con2.execute("DELETE FROM otp_groups WHERE chat_id=?", (cid,))
        con2.commit(); con2.close()
        await q.edit_message_text(f"✅ OTP group removed: {cid}")
    con.close()

# ---------- OTP auto-forward ----------
import re as _re

OTP_RE = _re.compile(
    r"(?i)\b(?:verification\s+code|otp|one[- ]?time\s*(?:pass(?:word|code)?|code|pin)|"
    r"passcode|access\s*code|confirmation\s*code|security\s*code|captcha|code|pin)\b"
    r"[^\d]{0,25}(\d{4,8})"
)
PLAIN_DIGITS_RE = _re.compile(r"(?<!\d)(\d{4,8})(?!\d)")


def extract_otp(message: str) -> str:
    if not message:
        return ""
    import re as _re0
    text = _re0.sub(r"(?<=\d)[\-‐‑‒–—](?=\d)", "", message)  # 547-686 -> 547686
    m = OTP_RE.search(text)
    if m:
        return m.group(1)
    m = PLAIN_DIGITS_RE.search(text)
    return m.group(1) if m else ""


def mask_num(number: str) -> str:
    d = _re.sub(r"\D", "", number or "")
    if len(d) <= 4:
        return "+" + d if d else "-"
    return f"+{d[:4]}{chr(8226) * 4}{d[-3:]}"


def build_forward_text(flag: str, iso: str, app_name: str, svc_em: str,
                       masked: str, otp: str, prefix: str) -> str:
    fmt = get_setting("otp_format", "v0.2")
    ov = get_setting("otp_visibility", "show")
    pd = get_setting("prefix_display", "ON")
    otp_t = otp if (otp and ov == "show") else ("••••" if otp else "-")
    if fmt == "v0.1":
        return f"🔔 {app_name}\n📱 {masked}\n🔐 OTP: {otp_t}"
    lines = ["◢◤ 𝙎𝙔𝙍𝙭_𝙊𝙏𝙋 ◥◣",
             f"🌍 COUNTRY › {flag} {iso}",
             f"💬 SERVICE › {svc_em} {app_name}",
             f"📱 NUMBER  › {masked}",
             f"🔐 OTP     › {otp_t}"]
    if pd == "ON":
        lines.append(f"📨 PREFIX  › {prefix}")
    lines.append("◢◤ @yaufee ◥◣")
    return "\n".join(lines)


def _poll_panels_once(seen: set) -> list:
    """Fetch recent CDR from all ON panels. Returns new forward texts."""
    from datetime import timedelta
    from country import country_info, service_emoji
    now = datetime.now()
    fdate2 = now.strftime("%Y-%m-%d %H:%M:%S")
    fdate1 = (now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    con = db()
    panels = con.execute("SELECT * FROM panels WHERE status='ON'").fetchall()
    pend_orders = con.execute("SELECT id, user_id, number FROM orders WHERE status='pending'").fetchall()
    pend_orders = [(o["id"], o["user_id"], _re.sub(r"\D", "", o["number"] or "")) for o in pend_orders]
    con.close()
    out = []
    for p in panels:
        try:
            url = p["url"] if "url" in p.keys() else ""
            pu = p["puser"] if "puser" in p.keys() else ""
            pp = p["ppass"] if "ppass" in p.keys() else ""
        except Exception:
            continue
        if not url or not pu:
            continue
        try:
            res = _get_client(p["id"], url, pu, pp, proxy=_row_proxy(p),
                              flavor=_row_flavor(p), api_base=_row_api(p), api_token=_row_token(p)).fetch_cdr(fdate1, fdate2, limit=100)
        except CooldownError:
            continue
        except Exception:
            continue
        for cells in res["rows"]:
            key = f"{p['id']}|" + "|".join(cells)
            if key in seen:
                continue
            seen.add(key)
            try:
                date, number, cli = cells[0], cells[2], cells[3]
            except IndexError:
                continue
            full = _re.sub(r"\D", "", number or "")
            flag, iso, _name, dial = country_info(full)
            otp = _row_otp(cells)
            app_name = (cli or "SMS").strip() or "SMS"
            masked = f"+{dial}SYRx{full[-3:]}" if dial and len(full) > 3 else mask_num(number)
            try:
                plen = max(4, min(10, int(get_setting("prefix_length", "7"))))
            except ValueError:
                plen = 7
            prefix = full[:plen] if len(full) >= plen else full
            out.append(build_forward_text(flag, iso, app_name, service_emoji(cli),
                                          masked, otp, prefix))
            if get_setting("checker_mode", "ON") != "ON":
                continue
            # pending number-order match -> DM user
            for oid, o_uid, od in pend_orders:
                if od and len(od) >= 7 and len(full) >= 7 and (full == od or full.endswith(od) or od.endswith(full)):
                    try:
                        con2 = db()
                        con2.execute("UPDATE orders SET status='completed', otp=? WHERE id=? AND status='pending'",
                                     (otp, oid))
                        con2.commit(); con2.close()
                    except Exception:
                        pass
                    _pending_dms.append((o_uid,
                        f"🔐 OTP Received\n\n📱 App: {app_name}\n📞 Number: {masked}\n"
                        f"🔐 OTP: `{otp or '-'}`"))
                    pend_orders = [x for x in pend_orders if x[0] != oid]
                    break
    global _last_poll
    _last_poll = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return out


async def otp_poller(app):
    import config as _cfg
    seen: set = set()
    first = True
    print("OTP poller started", flush=True)
    while True:
        try:
            poll_s = int(get_setting("poll_seconds", str(_cfg.POLL_SECONDS)))
        except ValueError:
            poll_s = 20
        try:
            news = await asyncio.to_thread(_poll_panels_once, seen)
            if first:
                first = False  # purano record forward হবে না, শুধু নতুন
                news = []
            groups = get_otp_groups()
            for txt in news[:20]:
                for cid, _title in groups:
                    try:
                        await app.bot.send_message(cid, txt)
                    except Exception as e:
                        print("Forward failed:", cid, e, flush=True)
            while _pending_dms:
                o_uid, dtxt = _pending_dms.pop(0)
                try:
                    await app.bot.send_message(o_uid, dtxt, parse_mode="Markdown")
                except Exception as e:
                    print("DM failed:", o_uid, e, flush=True)
        except Exception as e:
            print("Poll error:", e, flush=True)
        await asyncio.sleep(poll_s)


async def _post_init(app):
    app.create_task(otp_poller(app))


# ---------- main ----------
def main():
    if not BOT_TOKEN or BOT_TOKEN.startswith("PUT_"):
        print("❌ BOT_TOKEN set korun (ENV BOT_TOKEN ba local_settings.py)।")
        return
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
