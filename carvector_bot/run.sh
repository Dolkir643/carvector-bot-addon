#!/usr/bin/with-contenv bashio

export BOT_TOKEN=$(bashio::config 'bot_token')
export CARVECTOR_LOGIN=$(bashio::config 'carvector_login')
export CARVECTOR_PASSWORD=$(bashio::config 'carvector_password')
export TELEGRAM_MANAGER_CHAT_ID=$(bashio::config 'manager_chat_id')
export STORAGE_PATH="/data"

mkdir -p /data
cd /usr/src/app
python -u tg_bot.py
