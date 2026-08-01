import asyncio
import os

from pyrogram import Client
from pyrogram.types import Message

from command import fox_command, fox_sudo, who_message
from requirements_installer import install_library

install_library("requests -U")

import requests


CALLS_BASE_URL = "https://calls.okcdn.ru"
CALLS_API_KEY = "CHKIPMKGDIHBABABA"
SESSION_DATA = '{"device_id":"telega_alert","version":2,"client_version":"android_8","client_type":"SDK_ANDROID"}'


def is_telega_user(user_id: int) -> bool:
    try:
        user_id = int(user_id)
        if user_id <= 0:
            return False

        auth_response = requests.post(
            f"{CALLS_BASE_URL}/api/auth/anonymLogin",
            data={
                "application_key": CALLS_API_KEY,
                "session_data": SESSION_DATA,
            },
            headers={"Accept": "application/json"},
            timeout=12,
        )
        auth_response.raise_for_status()
        session_key = str((auth_response.json() or {}).get("session_key") or "").strip()
        if not session_key:
            return False

        lookup_response = requests.post(
            f"{CALLS_BASE_URL}/api/vchat/getOkIdsByExternalIds",
            data={
                "application_key": CALLS_API_KEY,
                "session_key": session_key,
                "externalIds": f'[{{"id":"{user_id}","ok_anonym":false}}]',
            },
            headers={"Accept": "application/json"},
            timeout=12,
        )
        lookup_response.raise_for_status()
        ids = (lookup_response.json() or {}).get("ids") or []

        for item in ids:
            external = (item or {}).get("external_user_id") or {}
            if str(external.get("id") or "") == str(user_id):
                return True
        return False
    except Exception:
        return False



@Client.on_message(fox_command("telega", "TelegaDetector", os.path.basename(__file__), "[reply/@username/id]") & fox_sudo())
async def telega_handler(client, message):
    message = await who_message(client, message)
    parts = message.text.split(maxsplit=1)

    if len(parts) >= 2:
        target = parts[1].strip()
        try:
            if target.startswith("@"):
                user = await client.get_users(target)
                user_id = user.id
            else:
                user_id = int(target)
                user = await client.get_users(user_id)
        except Exception:
            return await message.edit("Введите айди/@ пользователя или ответь на сообщение")
    elif message.reply_to_message and message.reply_to_message.from_user:
        user_id = message.reply_to_message.from_user.id
        user = await client.get_users(user_id)
    else:
        return await message.edit("Введите айди/@ пользователя или ответь на сообщение")

    first_name = user.first_name or ""
    last_name = user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    telega_check = await asyncio.to_thread(is_telega_user, user_id)

    if telega_check:
        await message.edit(f"🚨 <b>{full_name}</b> использует Telega или использовал его ранее")
    else:
        await message.edit(f"✅ <b>{full_name}</b> не использует Telega")

    
