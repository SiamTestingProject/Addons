# -*- coding: utf-8 -*-
import os
import logging

from pyrogram import Client

from command import zel_command, zel_sudo, who_message, get_text
from modules.core.settings.main_settings import file_list

filename = os.path.basename(__file__)
Module_Name = 'Uploadmod'

LANGUAGES = {
    "en": {
        "caption": "<emoji id='5283051451889756068'>🦊</emoji> Module `{module_name}`\nfor Zelretch <emoji id='5283051451889756068'>🦊</emoji>\n<b>You can install the module by replying [prefix]loadmod</b>",
        "error": "<emoji id='5210952531676504517'>❌</emoji> **An error has occurred.**\nLog: {error}"
    },
    "ru": {
        "caption": "<emoji id='5283051451889756068'>🦊</emoji> Модуль `{module_name}`\nдля Zelretch <emoji id='5283051451889756068'>🦊</emoji>\n<b>Вы можете установить модуль ответом [prefix]loadmod</b>",
        "error": "<emoji id='5210952531676504517'>❌</emoji> **Произошла ошибка.**\nЛог: {error}"
    },
    "ua": {
        "caption": "<emoji id='5283051451889756068'>🦊</emoji> Модуль `{module_name}`\nдля Zelretch <emoji id='5283051451889756068'>🦊</emoji>\n<b>Ви можете встановити модуль відповіддю [prefix]loadmod</b>",
        "error": "<emoji id='5210952531676504517'>❌</emoji> **Сталася помилка.**\nЛог: {error}"
    }
}


@Client.on_message(zel_command("uploadmod", Module_Name, filename, "[module name]") & zel_sudo())
async def uploadmod(client, message):
    message = await who_message(client, message)
    try:
        from command import my_prefix
        module_name = message.text.replace(f'{my_prefix()}uploadmod', '')
        params = module_name.split()
        module_name = params[0]
        file = file_list[module_name]
        
        await client.send_document(
            message.chat.id,
            f"modules/loaded/{file}",
            caption=get_text("uploadmod", "caption", LANGUAGES=LANGUAGES, module_name=module_name),
            message_thread_id=message.message_thread_id
        )
        await message.delete()
    except Exception as error:
        logging.exception("[Command: uploadmod] Module upload failed: %s", error)
        await message.edit(get_text("uploadmod", "error", LANGUAGES=LANGUAGES, error=str(error)))
