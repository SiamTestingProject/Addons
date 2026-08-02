# -*- coding: utf-8 -*-
import os
import shutil
import traceback
import zipfile
from pathlib import Path

import wget
from pyrogram import Client
from pyrogram.types import Message

from command import zel_command, zel_sudo, who_message, get_text

filename = os.path.basename(__file__)
Module_Name = 'Restarter'

LANGUAGES = {
    "en": {
        "updating": "<emoji id='5264727218734524899'>🔄</emoji> **Updating {repo_type}...**",
        "update_success": "<emoji id='5237699328843200968'>✅</emoji> **Zelretch successfully updated\n<emoji id='5264727218734524899'>🔄</emoji> Restarting...**",
        "error_occurred": "<emoji id='5210952531676504517'>❌</emoji> **An error occurred:**\n\n`{error}`",
        "restarting": "<emoji id='5264727218734524899'>🔄</emoji> **Restarting Zelretch...**",
        "restart_error": "<emoji id='5210952531676504517'>❌</emoji> **An error occurred...**",
        "update_not_configured": "⚙️ <b>Update source is not configured.</b> Set <code>ZELRETCH_UPDATE_URL</code> or <code>ZELRETCH_BETA_UPDATE_URL</code>."
    },
    "ru": {
        "updating": "<emoji id='5264727218734524899'>🔄</emoji> **Обновление {repo_type}...**",
        "update_success": "<emoji id='5237699328843200968'>✅</emoji> **Юзербот успешно обновлен\n<emoji id='5264727218734524899'>🔄</emoji> Перезапуск...**",
        "error_occurred": "<emoji id='5210952531676504517'>❌</emoji> **Произошла ошибка:**\n\n`{error}`",
        "restarting": "<emoji id='5264727218734524899'>🔄</emoji> **Перезапуск юзербота...**",
        "restart_error": "<emoji id='5210952531676504517'>❌</emoji> **Произошла ошибка...**",
        "update_not_configured": "⚙️ <b>Источник обновления не настроен.</b> Укажите <code>ZELRETCH_UPDATE_URL</code> или <code>ZELRETCH_BETA_UPDATE_URL</code>."
    },
    "ua": {
        "updating": "<emoji id='5264727218734524899'>🔄</emoji> **Оновлення {repo_type}...**",
        "update_success": "<emoji id='5237699328843200968'>✅</emoji> **Юзербот успішно оновлено\n<emoji id='5264727218734524899'>🔄</emoji> Перезавантаження...**",
        "error_occurred": "<emoji id='5210952531676504517'>❌</emoji> **Сталася помилка:**\n\n`{error}`",
        "restarting": "<emoji id='5264727218734524899'>🔄</emoji> **Перезапуск юзербота...**",
        "restart_error": "<emoji id='5210952531676504517'>❌</emoji> **Сталася помилка...**",
        "update_not_configured": "⚙️ <b>Джерело оновлення не налаштовано.</b> Вкажіть <code>ZELRETCH_UPDATE_URL</code> або <code>ZELRETCH_BETA_UPDATE_URL</code>."
    }
}


def restart_executor(chat_id=None, message_id=None, text=None, thread=None):
    # Persist configuration, aliases, modules, and triggers before replacing the process.
    try:
        from mongodb_storage import sync_runtime_state

        sync_runtime_state("before_restart")
    except Exception as sync_error:
        print(f"[MongoDB] Sync before restart failed: {sync_error}")
        raise
    if os.name == "nt":
        os.execvp(
            "python",
            [
                "python",
                "main.py",
                f"{chat_id}",
                f"{message_id}",
                f"{text}",
                f"{thread}" if thread else "None",
            ],
        )
    else:
        os.execvp(
            "python3",
            [
                "python3",
                "main.py",
                f"{chat_id}",
                f"{message_id}",
                f"{text}",
                f"{thread}" if thread else "None",
            ],
        )


async def restart(message: Message, restart_type):
    from operational_logger import flush_operational_logs, report_event

    if restart_type == "update":
        text = "1"
    else:
        text = "2"
    thread_id = message.message_thread_id if message.message_thread_id else None
    chat_id = message.chat.username if message.chat.username else message.chat.id
    restart_metadata = {
        "restart_type": restart_type,
        "chat_id": chat_id,
        "message_id": message.id,
    }
    report_event(
        "INFO",
        "ZELRETCH_RESTART",
        "A Zelretch restart was requested.",
        metadata=restart_metadata,
    )
    report_event(
        "INFO",
        "ZELRETCH_SHUTDOWN",
        "The current Zelretch process is shutting down for a planned restart.",
        metadata=restart_metadata,
    )
    await flush_operational_logs(4.0)
    restart_executor(chat_id, message.id, text, thread_id)


async def update_repository(client, message, repo_url, repo_type):
    try:
        try:
            os.remove("temp/archive.zip")
        except:
            pass

        # Upstream updates must not remove the Hugging Face, MongoDB, dot-prefix,
        # or inline-help deployment integration from this build.
        protected_paths = [
            ".gitattributes",
            "Dockerfile",
            "README.md",
            "requirements.txt",
            "main.py",
            "mongodb_storage.py",
            "prestarter.py",
            "command.py",
            "inline_help_bot.py",
            "operational_logger.py",
            "modules/core/restarter.py",
            "modules/core/plugin_loader.py",
            "modules/core/loadmod.py",
            "modules/core/help.py",
            "web_auth/web_auth.py",
        ]
        protected_files = {}
        for protected_path in protected_paths:
            file_path = Path(protected_path)
            if file_path.is_file():
                protected_files[protected_path] = file_path.read_bytes()

        await message.edit(get_text("restarter", "updating", LANGUAGES=LANGUAGES, repo_type=repo_type))

        wget.download(repo_url, 'temp/archive.zip')

        with zipfile.ZipFile("temp/archive.zip", "r") as zip_ref:
            file_list = zip_ref.namelist()
            root_folder = None
            for file in file_list:
                if file.endswith('/') and file.count('/') == 1:
                    root_folder = file.strip('/')
                    break
            
            if not root_folder:
                raise Exception("Not found root dir")

            zip_ref.extractall("temp/")

        os.remove("temp/archive.zip")
        shutil.make_archive("temp/archive", "zip", f"temp/{root_folder}/")
        with zipfile.ZipFile("temp/archive.zip", "r") as zip_ref:
            zip_ref.extractall(".")

        os.remove("temp/archive.zip")
        shutil.rmtree(f"temp/{root_folder}")

        for protected_path, protected_content in protected_files.items():
            file_path = Path(protected_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(protected_content)

        await message.edit(get_text("restarter", "update_success", LANGUAGES=LANGUAGES))
        await restart(message, restart_type="update")
        
    except Exception as e:
        from operational_logger import report_exception

        error_traceback = traceback.format_exc()
        report_exception(
            "ERROR",
            "UPDATE_ERROR",
            f"The {repo_type} update process failed.",
            e,
            metadata={"repo_url": repo_url, "repo_type": repo_type},
        )
        error_message = get_text("restarter", "error_occurred", LANGUAGES=LANGUAGES, error=str(e))

        if len(error_message) > 4000:
            error_message = error_message[:4000] + "..."
        
        await message.edit(error_message)


# Restart
@Client.on_message(zel_command("restart", Module_Name, filename) & zel_sudo())
async def restart_get(client, message):
    message = await who_message(client, message)
    try:
        await message.edit(get_text("restarter", "restarting", LANGUAGES=LANGUAGES))
        await restart(message, restart_type="restart")
    except Exception as error:
        from operational_logger import report_exception

        report_exception(
            "ERROR",
            "RESTART_ERROR",
            "The restart command failed before the process could be replaced.",
            error,
        )
        await message.edit(get_text("restarter", "restart_error", LANGUAGES=LANGUAGES))


# Update main
@Client.on_message(zel_command("update", Module_Name, filename) & zel_sudo())
async def update(client, message):
    message = await who_message(client, message)
    repo_url = (os.environ.get("ZELRETCH_UPDATE_URL") or "").strip()
    if not repo_url:
        return await message.edit(get_text("restarter", "update_not_configured", LANGUAGES=LANGUAGES))
    await update_repository(client, message, repo_url, "main")


# Update beta
@Client.on_message(zel_command("beta", Module_Name, filename) & zel_sudo())
async def update_beta(client, message):
    message = await who_message(client, message)
    repo_url = (os.environ.get("ZELRETCH_BETA_UPDATE_URL") or "").strip()
    if not repo_url:
        return await message.edit(get_text("restarter", "update_not_configured", LANGUAGES=LANGUAGES))
    await update_repository(client, message, repo_url, "beta")
