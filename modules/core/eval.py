# -*- coding: utf-8 -*-
import os
import logging
import sys
from io import StringIO

from pyrogram import Client

from command import zel_command, zel_sudo, who_message, get_text

LANGUAGES = {
    "en": {
        "success": """<emoji id='5300928913956938544'>👩‍💻</emoji> <b>Code:</b>
<code>{code}</code>

<emoji id='5447410659077661506'>🌐</emoji> <b>Result</b>:
<code>{result}</code>""",
        "error": """<emoji id='5300928913956938544'>👩‍💻</emoji> <b>Code:</b>
<code>{code}</code>

<emoji id='5447410659077661506'>🌐</emoji> <b>Result</b>:
<code>{error_type}: {error_message}</code>"""
    },
    "ru": {
        "success": """<emoji id='5300928913956938544'>👩‍💻</emoji> <b>Код:</b>
<code>{code}</code>

<emoji id='5447410659077661506'>🌐</emoji> <b>Результат</b>:
<code>{result}</code>""",
        "error": """<emoji id='5300928913956938544'>👩‍💻</emoji> <b>Код:</b>
<code>{code}</code>

<emoji id='5447410659077661506'>🌐</emoji> <b>Результат</b>:
<code>{error_type}: {error_message}</code>"""
    },
    "ua": {
        "success": """<emoji id='5300928913956938544'>👩‍💻</emoji> <b>Код:</b>
<code>{code}</code>

<emoji id='5447410659077661506'>🌐</emoji> <b>Результат</b>:
<code>{result}</code>""",
        "error": """<emoji id='5300928913956938544'>👩‍💻</emoji> <b>Код:</b>
<code>{code}</code>

<emoji id='5447410659077661506'>🌐</emoji> <b>Результат</b>:
<code>{error_type}: {error_message}</code>"""
    }
}

@Client.on_message(zel_command("eval", "Eval", os.path.basename(__file__), "[code/reply]") & zel_sudo())
async def user_exec(client, message):
    message = await who_message(client, message)
    reply = message.reply_to_message
    code = ""
    try:
        code = message.text.split(" ", maxsplit=1)[1]
    except IndexError:
        try:
            code = message.text.split(" \n", maxsplit=1)[1]
        except IndexError:
            pass

    result = sys.stdout = StringIO()
    try:
        exec(code)
        result_text = get_text("eval", "success", LANGUAGES=LANGUAGES, 
                              code=code, result=result.getvalue())
        await message.edit(result_text)
    except Exception as e:
        logging.exception("[Command: eval] Evaluation failed: %s", e)
        error_text = get_text("eval", "error", LANGUAGES=LANGUAGES,
                             code=code, error_type=type(e).__name__, error_message=str(e))
        await message.edit(error_text)