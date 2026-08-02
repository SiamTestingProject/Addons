# -*- coding: utf-8 -*-
import configparser
import html
import os
import logging
import random
import re
from pathlib import Path

from pyrogram import Client
from telegraph import Telegraph

from command import zel_command, zel_sudo, who_message, get_text, my_prefix
from modules.core.settings.main_settings import module_list, version

# Default
DEFAULT_HELP_IMAGE = os.environ.get("PROJECT_IMAGE_URL", "https://huggingface.co/spaces/" + os.environ.get("SPACE_ID", "SiamReal/VPS") + "/resolve/main/photos/Zelretch.jpg")
THEME_PATH = "userdata/theme.ini"
CACHE_DIR = "temp"
CACHE_CONTENT_FILE = os.path.join(CACHE_DIR, "help_content.txt")
CACHE_LINK_FILE = os.path.join(CACHE_DIR, "help_link.txt")

LANGUAGES = {
    "en": {
        "loading": "Opening the Zelretch command center...",
        "commands_list": "✨ Explore commands",
        "default_text": """
✨ <b>ZELRETCH ONLINE</b>
<i>Precision tools. One command center.</i>

◆ <b>Version:</b> {version}
◆ <b>Modules:</b> {modules_count}
◆ <b>Prefix:</b> <code>{prefix}</code>

◆ <b>Developer:</b> <a href="https://t.me/Ch0wdhury_Siam">@Ch0wdhury_Siam</a>
"""
    },
    "ru": {
        "loading": "Открываю центр команд Zelretch...",
        "commands_list": "✨ Команды",
        "default_text": """
✨ <b>ZELRETCH ONLINE</b>
<i>Точные инструменты. Единый центр команд.</i>

◆ <b>Версия:</b> {version}
◆ <b>Модули:</b> {modules_count}
◆ <b>Префикс:</b> <code>{prefix}</code>

◆ <b>Разработчик:</b> <a href="https://t.me/Ch0wdhury_Siam">@Ch0wdhury_Siam</a>
"""
    },
    "ua": {
        "loading": "Відкриваю центр команд Zelretch...",
        "commands_list": "✨ Команди",
        "default_text": """
✨ <b>ZELRETCH ONLINE</b>
<i>Точні інструменти. Єдиний центр команд.</i>

◆ <b>Версія:</b> {version}
◆ <b>Модулі:</b> {modules_count}
◆ <b>Префікс:</b> <code>{prefix}</code>

◆ <b>Розробник:</b> <a href="https://t.me/Ch0wdhury_Siam">@Ch0wdhury_Siam</a>
"""
    }
}

def get_help_image():
    if not Path(THEME_PATH).exists():
        return DEFAULT_HELP_IMAGE

    try:
        config = configparser.ConfigParser()
        config.read(THEME_PATH, encoding='utf-8')
        return config.get("help", "image", fallback=DEFAULT_HELP_IMAGE)
    except:
        return DEFAULT_HELP_IMAGE

def get_modules_content():
    content = []
    for module_name, commands in module_list.items():
        if isinstance(commands, list):
            commands = " | ".join(commands)
        content.append(f"{module_name}:{commands}")
    return "\n".join(content)

def get_cached_telegraph_link():
    if os.path.exists(CACHE_LINK_FILE) and os.path.exists(CACHE_CONTENT_FILE):
        try:
            with open(CACHE_CONTENT_FILE, 'r', encoding='utf-8') as f:
                cached_content = f.read().strip()
            
            current_content = get_modules_content()
            
            if cached_content == current_content:
                with open(CACHE_LINK_FILE, 'r', encoding='utf-8') as f:
                    return f.read().strip()
        except:
            pass
    return None

def cache_telegraph_link(link):
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    try:
        current_content = get_modules_content()
        with open(CACHE_CONTENT_FILE, 'w', encoding='utf-8') as f:
            f.write(current_content)
        with open(CACHE_LINK_FILE, 'w', encoding='utf-8') as f:
            f.write(link)
    except Exception as e:
        print(f"Error caching telegraph link: {e}")

def create_html_file(content):
    os.makedirs(CACHE_DIR, exist_ok=True)
    file_name = f"help_{random.randint(10000, 99999)}.html"
    file_path = os.path.join(CACHE_DIR, file_name)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Zelretch Command Center</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .module {{ margin-bottom: 20px; }}
        .command {{ margin-left: 20px; font-family: monospace; }}
    </style>
</head>
<body>
    <h1>Zelretch Command Center</h1>
    {content}
</body>
</html>""")
    
    return file_path

def get_help_caption():
    """Build the help card caption without embedding the command list as a URL."""
    if Path(THEME_PATH).exists():
        try:
            config = configparser.ConfigParser()
            config.read(THEME_PATH, encoding='utf-8')
            custom_text = config.get("help", "text", fallback=None)
            if custom_text and custom_text.strip() and custom_text != "Not set":
                # Existing themes may still contain the old {commands_link}
                # anchor. Keep its visible label but remove the hyperlink; the
                # companion bot supplies the real inline command button.
                custom_text = re.sub(
                    r'<a\s+href=["\']\{commands_link\}["\']>(.*?)</a>',
                    r'\1',
                    custom_text,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                aliases = {
                    '{version}': version,
                    '{modules_count}': str(len(module_list)),
                    '{prefix}': my_prefix(),
                    '{commands_link}': '',
                }
                for alias, value in aliases.items():
                    custom_text = custom_text.replace(alias, str(value))
                return custom_text.strip()
        except Exception:
            pass

    default_text = get_text("help", "default_text", LANGUAGES=LANGUAGES)
    return default_text.format(
        version=version,
        modules_count=len(module_list),
        prefix=my_prefix(),
        commands_link="",
    ).strip()

def get_help_text():
    cached_link = get_cached_telegraph_link()
    
    lists = []
    for module_name, commands in module_list.items():
        text = ""
        if isinstance(commands, list):
            for i in commands:
                text += f"{i} | "
            text = text[:-2]
            commands = text
        command_list = [cmd.strip() for cmd in commands.split("|")]

        escaped_module_name = html.escape(str(module_name), quote=True)
        escaped_commands = [html.escape(str(cmd), quote=True) for cmd in command_list]
        module_block = [
            f"➣ Module <b>[{escaped_module_name}]</b>",
            *[f"Command: <code>{cmd}</code>" for cmd in escaped_commands],
            "" 
        ]
        lists.extend(module_block)

    a = "<br>".join(lists)
    
    html_file_path = None
    
    if cached_link:
        link = cached_link
    else:
        try:
            telegraph = Telegraph()
            telegraph.create_account(short_name='Zelretch')
            page = telegraph.create_page(
                f'Zelretch Command Center {random.randint(10000, 99999)}', 
                html_content=a
            )
            link = f"https://telegra.ph/{page['path']}"
            cache_telegraph_link(link)
        except Exception as e:
            html_file_path = create_html_file(a)
            link = "https://telegra.ph/"
    
    custom_text = None
    if Path(THEME_PATH).exists():
        try:
            config = configparser.ConfigParser()
            config.read(THEME_PATH, encoding='utf-8')
            custom_text = config.get("help", "text", fallback=None)
            if custom_text and custom_text.strip() and custom_text != "Not set":
                aliases = {
                    '{version}': version,
                    '{modules_count}': str(len(module_list)),
                    '{prefix}': my_prefix(),
                    '{commands_link}': link,
                }
                for alias, value in aliases.items():
                    custom_text = custom_text.replace(alias, str(value))
                return custom_text, html_file_path
        except Exception as e:
            pass
    
    default_text = get_text("help", "default_text", LANGUAGES=LANGUAGES)
    text = default_text.format(
        version=version,
        modules_count=len(module_list),
        prefix=my_prefix(),
        commands_link=link
    )
    return text, html_file_path

@Client.on_message(zel_command("help", "Help", os.path.basename(__file__)) & zel_sudo())
async def helps(client, message):
    message = await who_message(client, message)

    # User accounts cannot attach Telegram inline keyboards directly. When a
    # BOT_TOKEN is configured, query the bundled companion inline bot and send
    # its result into the current chat.
    try:
        from inline_help_bot import send_inline_help

        if await send_inline_help(client, message):
            await message.delete()
            return
    except Exception:
        pass

    # Preserve the original direct-media help output as a fallback when the
    # optional companion bot is not configured or inline mode is unavailable.
    html_file_path = None
    try:
        image_url = get_help_image()
        loading_text = get_text("help", "loading", LANGUAGES=LANGUAGES)
        
        if image_url.split(".")[-1].lower() in ["mp4", "mov", "avi", "mkv", "webm"]:
            da = await client.send_video(
                message.chat.id, 
                video=image_url, 
                caption=loading_text, 
                message_thread_id=message.message_thread_id
            )

        elif image_url.split(".")[-1].lower() == "gif":
            da = await client.send_animation(
                message.chat.id, 
                animation=image_url, 
                caption=loading_text, 
                message_thread_id=message.message_thread_id
            )
        else:
            da = await client.send_photo(
            message.chat.id, 
            photo=image_url, 
            caption=loading_text, 
            message_thread_id=message.message_thread_id 
        )
        await message.delete()
        caption, html_file_path = get_help_text()
        await client.edit_message_caption(message.chat.id, da.id, caption)
        
        if html_file_path:
            commands_list_text = get_text("help", "commands_list", LANGUAGES=LANGUAGES)
            await client.send_document(
                message.chat.id,
                document=html_file_path,
                caption=commands_list_text,
                message_thread_id=message.message_thread_id
            )
            os.remove(html_file_path)
            
    except Exception as e:
        logging.exception("[Command: help] Primary help rendering failed: %s", e)
        try:
            da = await client.send_photo(
                message.chat.id, 
                photo=DEFAULT_HELP_IMAGE, 
                caption=loading_text, 
                message_thread_id=message.message_thread_id
            )
            await message.delete()
            caption, html_file_path = get_help_text()
            await client.edit_message_caption(message.chat.id, da.id, caption)
            
            if html_file_path:
                commands_list_text = get_text("help", "commands_list", LANGUAGES=LANGUAGES)
                await client.send_document(
                    message.chat.id,
                    document=html_file_path,
                    caption=commands_list_text,
                    message_thread_id=message.message_thread_id
                )
                os.remove(html_file_path)
                
        except:
            try:
                da = await client.send_photo(
                    message.chat.id, 
                    photo="photos/Zelretch.jpg", 
                    caption=loading_text, 
                    message_thread_id=message.message_thread_id
                )
                await message.delete()
                caption, html_file_path = get_help_text()
                await client.edit_message_caption(message.chat.id, da.id, caption)
                
                if html_file_path:
                    commands_list_text = get_text("help", "commands_list", LANGUAGES=LANGUAGES)
                    await client.send_document(
                        message.chat.id,
                        document=html_file_path,
                        caption=commands_list_text,
                        message_thread_id=message.message_thread_id
                    )
                    os.remove(html_file_path)
                    
            except:
                await message.edit(loading_text)
                caption, html_file_path = get_help_text()
                await message.edit(caption)
                
                if html_file_path:
                    commands_list_text = get_text("help", "commands_list", LANGUAGES=LANGUAGES)
                    await client.send_document(
                        message.chat.id,
                        document=html_file_path,
                        caption=commands_list_text,
                        message_thread_id=message.message_thread_id
                    )
                    os.remove(html_file_path)