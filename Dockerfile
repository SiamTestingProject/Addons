FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DOCKER=True \
    PORT=7860 \
    SPACE_PORT=7860 \
    AUTO_TELEGRAM_SETUP=true \
    AUTO_ADDONS=true \
    ADDONS_REPO=https://github.com/SiamTestingProject/Addons \
    ADDONS_BRANCH=main \
    HOME=/home/user \
    PATH="/home/user/venv/bin:/home/user/.local/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl wget unzip git openssh-client \
    build-essential gcc g++ python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user

WORKDIR /home/user/app
COPY --chown=user:user . /home/user/app

RUN python -m venv /home/user/venv \
    && /home/user/venv/bin/python -m pip install --upgrade pip setuptools wheel \
    && /home/user/venv/bin/python -m pip install --no-cache-dir -r requirements.txt \
    && /home/user/venv/bin/python -m pip install --no-cache-dir tgcrypto uv \
    && mkdir -p /home/user/app/userdata /home/user/app/triggers \
       /home/user/app/temp /home/user/app/modules/loaded \
       /home/user/app/broken_modules /home/user/space_status \
    && cp /home/user/app/photos/Zelretch.jpg /home/user/space_status/Zelretch.jpg \
    && printf '%s\n' \
        '<!doctype html>' \
        '<html lang="en">' \
        '<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Zelretch</title></head>' \
        '<body style="margin:0;background:#130818;color:#f8eefc;font-family:system-ui,Arial,sans-serif;">' \
        '<main style="max-width:900px;margin:40px auto;padding:0 20px;text-align:center;">' \
        '<img src="/Zelretch.jpg" alt="Zelretch" style="width:100%;border-radius:24px;box-shadow:0 16px 50px #0008;">' \
        '<h1 style="font-size:2.4rem;margin-bottom:.3rem;">Zelretch is online</h1>' \
        '<p style="color:#d7bfdc;">Telegram session and runtime state are synchronized through MongoDB.</p>' \
        '<p style="color:#aa8cb0;">Developer: Siam Chowdhury · @Ch0wdhury_Siam</p>' \
        '</main></body></html>' \
        > /home/user/space_status/index.html

RUN cat > /usr/local/bin/start-zelretch <<'EOF_START'
#!/usr/bin/env bash
set -euo pipefail

mkdir -p userdata triggers temp modules/loaded broken_modules

if [ -z "${MONGODB_URI:-}" ]; then
    echo "ERROR: MONGODB_URI is required. Add it as a Hugging Face Space secret." >&2
    exit 1
fi

auto_setup="${AUTO_TELEGRAM_SETUP:-true}"
auto_setup_normalized="$(printf '%s' "$auto_setup" | tr '[:upper:]' '[:lower:]')"
auto_setup_enabled=true
case "$auto_setup_normalized" in
    0|false|no|off|disabled) auto_setup_enabled=false ;;
esac

if [ -n "${LOG_CHANNEL_ID:-}" ] && [ -z "${BOT_TOKEN:-}" ]; then
    if [ "$auto_setup_enabled" = true ]; then
        echo "INFO: BOT_TOKEN is absent; Zelretch will restore or create its companion bot automatically." >&2
    else
        echo "WARNING: LOG_CHANNEL_ID is set but BOT_TOKEN is absent and automatic Telegram setup is disabled." >&2
    fi
fi

if [ -n "${BOT_TOKEN:-}" ] && [ -z "${LOG_CHANNEL_ID:-}" ]; then
    if [ "$auto_setup_enabled" = true ]; then
        echo "INFO: LOG_CHANNEL_ID is absent; Zelretch will restore or create a private logging channel automatically." >&2
    else
        echo "WARNING: BOT_TOKEN is set but LOG_CHANNEL_ID is absent and automatic Telegram setup is disabled." >&2
    fi
fi

if [ -z "${BOT_TOKEN:-}" ] && [ -z "${LOG_CHANNEL_ID:-}" ] && [ "$auto_setup_enabled" = true ]; then
    echo "INFO: Zelretch will restore or provision the companion bot and logging channel automatically." >&2
fi

python mongodb_storage.py restore

if [ -n "${API_ID:-}" ] && [ -n "${API_HASH:-}" ]; then
    python - <<'PY_CONFIG'
import configparser
import os
from pathlib import Path

path = Path("userdata/config.ini")
config = configparser.ConfigParser()
config.read(path)
if not config.has_section("pyrogram"):
    config.add_section("pyrogram")
config.set("pyrogram", "api_id", os.environ["API_ID"])
config.set("pyrogram", "api_hash", os.environ["API_HASH"])
config.set("pyrogram", "device_model", os.environ.get("DEVICE_MODEL", "Zelretch"))
if not config.has_section("prefix"):
    config.add_section("prefix")
config.set("prefix", "prefix", config.get("prefix", "prefix", fallback="."))
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("w", encoding="utf-8") as file:
    config.write(file)
PY_CONFIG
fi

if python mongodb_storage.py has-session; then
    python -m http.server "${PORT:-7860}" --bind 0.0.0.0 --directory /home/user/space_status &
fi

exec python main.py "$@"
EOF_START

RUN chmod +x /usr/local/bin/start-zelretch \
    && chown -R user:user /home/user/app /home/user/space_status /home/user/venv

USER user
EXPOSE 7860

CMD ["start-zelretch"]
