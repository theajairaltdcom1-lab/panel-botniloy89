@echo off
title Panel Bot Setup
echo === Panel Bot Setup ===
python --version || (echo Python install koren: https://www.python.org/downloads/ & pause & exit)
pip install -r requirements.txt
if not exist local_settings.py (
  set /p TOKEN="Bot Token (BotFather): "
  set /p ADMINS="Admin IDs (comma): "
  echo # Local secrets - NEVER commit> local_settings.py
  echo BOT_TOKEN = "%TOKEN%">> local_settings.py
  echo ADMIN_IDS = [%ADMINS%]>> local_settings.py
  echo local_settings.py banano hoyeche.
) else (
  echo local_settings.py ache - skip.
)
echo === Bot start hocche... ===
python -u bot.py
pause
