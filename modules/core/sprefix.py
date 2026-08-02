# -*- coding: utf-8 -*-
import configparser
import os

from pyrogram import Client

from command import zel_command, zel_sudo, who_message, get_text
from modules.core.restarter import restart

PATH_FILE = "userdata/config.ini"

config = configparser.ConfigParser()
config.read(PATH_FILE)

LANGUAGES = {
    "en": {
        "success": "<emoji id='5237699328843200968'>✅</emoji> <b>prefix [ <code>{prefix}</code> ] set!</b>\n<emoji id='5264727218734524899'>🔄</emoji> Restarting Zelretch...",
        "error": "<b>prefix don't be None</b>"
    },
    "ru": {
        "success": "<emoji id='5237699328843200968'>✅</emoji> <b>префикс [ <code>{prefix}</code> ] установлен!</b>\n<emoji id='5264727218734524899'>🔄</emoji> Перезапускаю юзербот...",
        "error": "<b>префикс не может быть пустым</b>"
    },
    "ua": {
        "success": "<emoji id='5237699328843200968'>✅</emoji> <b>префікс [ <code>{prefix}</code> ] встановлено!</b>\n<emoji id='5264727218734524899'>🔄</emoji> Перезавантажую юзербот...",
        "error": "<b>префікс не може бути порожнім</b>"
    }
}

@Client.on_message(zel_command(["sp", "setprefix"], "SetPrefix", os.path.basename(__file__), "[new prefix]") & zel_sudo())
async def sprefix(client, message):
    message = await who_message(client, message)
    if len(message.text.split()) > 1:
        prefixgett = message.text.split()[1]
        config.set("prefix", "prefix", prefixgett)
        with open(PATH_FILE, "w") as config_file:
            config.write(config_file)
        
        success_text = get_text("sprefix", "success", LANGUAGES=LANGUAGES, prefix=prefixgett)
        await message.edit(success_text)
        await restart(message, restart_type="restart")
    else:
        error_text = get_text("sprefix", "error", LANGUAGES=LANGUAGES)

        await message.edit(error_text)
