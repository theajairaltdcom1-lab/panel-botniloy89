#!/bin/bash
# Panel Bot Setup (Linux/VPS)
set -e
echo "=== Panel Bot Setup ==="
python3 --version
pip3 install -r requirements.txt
if [ ! -f local_settings.py ]; then
  read -p "Bot Token (BotFather): " TOKEN
  read -p "Admin IDs (comma): " ADMINS
  cat > local_settings.py <<EOF
# Local secrets - NEVER commit
BOT_TOKEN = "$TOKEN"
ADMIN_IDS = [$ADMINS]
EOF
  echo "local_settings.py banano hoyeche."
else
  echo "local_settings.py ache - skip."
fi
echo "=== Bot start hocche... ==="
python3 -u bot.py
