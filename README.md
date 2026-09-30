# Panel Bot

Telegram panel + number-stock + OTP forward bot.

## Setup (PC/VPS)

**Windows:** `setup.bat` chalao — token + admin ID dibe, bot cholbe.
**Linux:** `bash setup.sh`

Manual:
```
pip install -r requirements.txt
# local_settings.py banau:
BOT_TOKEN = "123:ABC..."
ADMIN_IDS = [111111]
python -u bot.py
```

## Deploy (Railway, 24/7)

1. Repo connect kore service banau (worker: `python -u bot.py`)
2. ENV: `BOT_TOKEN`, `ADMIN_IDS`, `POLL_SECONDS=20`
3. Deploy

## Features

- Panel: v1 (ServisSMS) / v2 (tempsms.io) / v3 (React API) / v4 (browser) / v5 (token API)
- OTP auto-forward (SYRx format) + order DM match
- Number stock (service/country), referral, wallet/withdraw, temp mail, traffic
- Admin / Master / Sub-admin roles, broadcast, backup
