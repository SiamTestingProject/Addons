# -*- coding: utf-8 -*-
"""Companion Kurigram bot for Zelretch's interactive command center."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Sequence

INLINE_BOT_USERNAME = os.environ.get("INLINE_BOT_USERNAME", "").strip().lstrip("@")
MODULES_PER_PAGE = 8
MEDIA_CAPTION_LIMIT = 900
TEXT_MESSAGE_LIMIT = 3800
DEVELOPER_URL = "https://github.com/ChowdhurySiam"
TELEGRAM_URL = "https://t.me/Ch0wdhury_Siam"

_bot_username: Optional[str] = INLINE_BOT_USERNAME or None
_bot_client: Optional[Any] = None


def _default_project_image() -> str:
    explicit = (os.environ.get("PROJECT_IMAGE_URL") or "").strip()
    if explicit:
        return explicit
    space_id = (os.environ.get("SPACE_ID") or "SiamReal/VPS").strip()
    return f"https://huggingface.co/spaces/{space_id}/resolve/main/photos/Zelretch.jpg"


DEFAULT_PROJECT_IMAGE = _default_project_image()

LABELS = {
    "en": {
        "all_commands": "✨ Explore commands",
        "choose_module": "Select a module to view its purpose and commands.",
        "module": "Module",
        "category": "Category",
        "page": "Page",
        "back": "⬅️ Modules",
        "home": "🏠 Home",
        "previous": "◀️",
        "next": "▶️",
        "developer": "Developer",
        "no_commands": "No public commands are registered for this module.",
        "unavailable": "The command center is temporarily unavailable.",
    },
    "ru": {
        "all_commands": "✨ Команды",
        "choose_module": "Выберите модуль, чтобы увидеть описание и команды.",
        "module": "Модуль",
        "category": "Категория",
        "page": "Страница",
        "back": "⬅️ Модули",
        "home": "🏠 Главная",
        "previous": "◀️",
        "next": "▶️",
        "developer": "Разработчик",
        "no_commands": "Для этого модуля нет публичных команд.",
        "unavailable": "Центр команд временно недоступен.",
    },
    "ua": {
        "all_commands": "✨ Команди",
        "choose_module": "Виберіть модуль, щоб переглянути опис і команди.",
        "module": "Модуль",
        "category": "Категорія",
        "page": "Сторінка",
        "back": "⬅️ Модулі",
        "home": "🏠 Головна",
        "previous": "◀️",
        "next": "▶️",
        "developer": "Розробник",
        "no_commands": "Для цього модуля немає публічних команд.",
        "unavailable": "Центр команд тимчасово недоступний.",
    },
}


def _labels() -> Dict[str, str]:
    try:
        from command import get_global_lang
        lang = get_global_lang()
    except Exception:
        lang = "en"
    return LABELS.get(lang, LABELS["en"])


def _sanitize_bot_html(text: str) -> str:
    return re.sub(
        r"<emoji\b[^>]*>(.*?)</emoji>",
        r"\1",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()


def _help_caption() -> str:
    try:
        from modules.core.help import get_help_caption
        return _sanitize_bot_html(get_help_caption())
    except Exception as exc:
        logging.warning("[InlineHelpBot] Unable to build help caption: %s", exc, exc_info=True)
        try:
            from command import my_prefix
            from modules.core.settings.main_settings import module_list, version
            prefix = my_prefix()
            modules_count = len(module_list)
        except Exception:
            prefix, modules_count, version = ".", 0, "3.0.0"
        return (
            "✨ <b>ZELRETCH ONLINE</b>\n"
            "<i>Precision tools. One command center.</i>\n\n"
            f"◆ <b>Version:</b> {html.escape(str(version))}\n"
            f"◆ <b>Modules:</b> {modules_count}\n"
            f"◆ <b>Prefix:</b> <code>{html.escape(prefix)}</code>\n\n"
            "◆ <b>Developer:</b> @Ch0wdhury_Siam"
        )


def _help_image() -> str:
    try:
        from modules.core.help import get_help_image
        image = str(get_help_image()).strip()
        return image or DEFAULT_PROJECT_IMAGE
    except Exception:
        return DEFAULT_PROJECT_IMAGE


def _module_snapshot() -> List[Dict[str, Any]]:
    try:
        from modules.core.settings.main_settings import (
            file_list,
            get_module_metadata,
            module_list,
        )

        snapshot: List[Dict[str, Any]] = []
        for module_name, commands in list(module_list.items()):
            if isinstance(commands, str):
                normalized = [part.strip() for part in commands.split("|") if part.strip()]
            elif isinstance(commands, Sequence):
                normalized = [str(command).strip() for command in commands if str(command).strip()]
            else:
                normalized = [str(commands).strip()] if str(commands).strip() else []
            filename = file_list.get(module_name, "")
            metadata = get_module_metadata(str(module_name), filename)
            snapshot.append(
                {
                    "key": str(module_name),
                    "filename": filename,
                    "commands": normalized,
                    **metadata,
                }
            )
        return sorted(
            snapshot,
            key=lambda item: (
                str(item.get("category", "")).casefold(),
                str(item.get("title", "")).casefold(),
            ),
        )
    except Exception as exc:
        logging.warning("[InlineHelpBot] Unable to read module catalog: %s", exc, exc_info=True)
        return []


def _keyboard(rows: List[List[Dict[str, str]]]) -> Any:
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = []
    for row in rows:
        rendered = []
        for button in row:
            if button.get("url"):
                rendered.append(InlineKeyboardButton(text=button["text"], url=button["url"]))
            else:
                rendered.append(
                    InlineKeyboardButton(
                        text=button["text"],
                        callback_data=button["callback_data"],
                    )
                )
        keyboard.append(rendered)
    return InlineKeyboardMarkup(keyboard)


def _home_keyboard(mode: str) -> Any:
    labels = _labels()
    return _keyboard(
        [
            [{"text": labels["all_commands"], "callback_data": f"zh{mode}:list:0"}],
            [
                {"text": "GitHub", "url": DEVELOPER_URL},
                {"text": "Telegram", "url": TELEGRAM_URL},
            ],
        ]
    )


def _input_text_content(text: str) -> Any:
    from pyrogram.enums import ParseMode
    from pyrogram.types import InputTextMessageContent
    try:
        from pyrogram.types import LinkPreviewOptions
        return InputTextMessageContent(
            message_text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception:
        return InputTextMessageContent(message_text=text, parse_mode=ParseMode.HTML)


def _build_inline_result() -> Any:
    from pyrogram.enums import ParseMode
    from pyrogram.types import (
        InlineQueryResultAnimation,
        InlineQueryResultArticle,
        InlineQueryResultPhoto,
        InlineQueryResultVideo,
    )

    caption = _help_caption()
    image = _help_image()
    lower = image.lower().split("?", 1)[0]
    is_remote = image.startswith(("https://", "http://"))

    if is_remote and lower.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return InlineQueryResultPhoto(
            id="zelretch-help-photo",
            photo_url=image,
            thumb_url=image,
            title="Zelretch Command Center",
            description=_labels()["all_commands"],
            caption=caption[:1024],
            parse_mode=ParseMode.HTML,
            reply_markup=_home_keyboard("c"),
        )
    if is_remote and lower.endswith(".gif"):
        return InlineQueryResultAnimation(
            id="zelretch-help-gif",
            animation_url=image,
            thumb_url=DEFAULT_PROJECT_IMAGE,
            title="Zelretch Command Center",
            caption=caption[:1024],
            parse_mode=ParseMode.HTML,
            reply_markup=_home_keyboard("c"),
        )
    if is_remote and lower.endswith(".mp4"):
        return InlineQueryResultVideo(
            id="zelretch-help-video",
            video_url=image,
            mime_type="video/mp4",
            thumb_url=DEFAULT_PROJECT_IMAGE,
            title="Zelretch Command Center",
            description=_labels()["all_commands"],
            caption=caption[:1024],
            parse_mode=ParseMode.HTML,
            reply_markup=_home_keyboard("c"),
        )
    return InlineQueryResultArticle(
        id="zelretch-help-text",
        title="Zelretch Command Center",
        description=_labels()["all_commands"],
        input_message_content=_input_text_content(caption[:4096]),
        reply_markup=_home_keyboard("t"),
    )


def _paginate_lines(header: str, lines: List[str], limit: int) -> List[str]:
    if not lines:
        return [header]
    pages: List[str] = []
    current = header
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current and current != header:
            pages.append(current)
            current = header
        remaining = line
        while len(f"{header}\n{remaining}") > limit:
            available = max(100, limit - len(header) - 1)
            pages.append(f"{header}\n{remaining[:available]}")
            remaining = remaining[available:]
        current = f"{header}\n{remaining}"
    if current:
        pages.append(current)
    return pages or [header]


def _list_view(mode: str, page: int) -> tuple[str, Any]:
    labels = _labels()
    modules = _module_snapshot()
    page_count = max(1, (len(modules) + MODULES_PER_PAGE - 1) // MODULES_PER_PAGE)
    page = max(0, min(page, page_count - 1))
    start = page * MODULES_PER_PAGE
    visible = modules[start : start + MODULES_PER_PAGE]
    categories = len({item.get("category") for item in modules})

    text = (
        "✨ <b>ZELRETCH COMMAND CENTER</b>\n"
        f"{html.escape(labels['choose_module'])}\n\n"
        f"◆ <b>Modules:</b> {len(modules)}\n"
        f"◆ <b>Categories:</b> {categories}\n"
        f"◆ <b>{html.escape(labels['page'])}:</b> {page + 1}/{page_count}"
    )

    rows: List[List[Dict[str, str]]] = []
    for row_start in range(0, len(visible), 2):
        row: List[Dict[str, str]] = []
        for relative_index, module in enumerate(visible[row_start : row_start + 2]):
            absolute_index = start + row_start + relative_index
            button_text = f"{module.get('icon', '🧩')} {module.get('title', module['key'])}"
            if len(button_text) > 31:
                button_text = f"{button_text[:28]}…"
            row.append(
                {
                    "text": button_text,
                    "callback_data": f"zh{mode}:module:{absolute_index}:0:{page}",
                }
            )
        rows.append(row)

    navigation: List[Dict[str, str]] = []
    if page > 0:
        navigation.append({"text": labels["previous"], "callback_data": f"zh{mode}:list:{page - 1}"})
    navigation.append({"text": labels["home"], "callback_data": f"zh{mode}:home"})
    if page + 1 < page_count:
        navigation.append({"text": labels["next"], "callback_data": f"zh{mode}:list:{page + 1}"})
    rows.append(navigation)
    return text, _keyboard(rows)


def _module_view(mode: str, module_index: int, command_page: int, list_page: int) -> tuple[str, Any]:
    labels = _labels()
    modules = _module_snapshot()
    if not modules:
        return _list_view(mode, 0)
    module_index = max(0, min(module_index, len(modules) - 1))
    module = modules[module_index]
    header = (
        f"{html.escape(str(module.get('icon', '🧩')))} "
        f"<b>{html.escape(str(module.get('title', module['key'])))}</b>\n"
        f"<i>{html.escape(str(module.get('description', 'Zelretch module.')))}</i>\n\n"
        f"◆ <b>{html.escape(labels['category'])}:</b> "
        f"{html.escape(str(module.get('category', 'Other')))}\n"
        "◆ <b>Commands</b>"
    )
    command_lines = [f"• <code>{html.escape(command)}</code>" for command in module["commands"]]
    if not command_lines:
        command_lines = [html.escape(labels["no_commands"])]
    limit = MEDIA_CAPTION_LIMIT if mode == "c" else TEXT_MESSAGE_LIMIT
    pages = _paginate_lines(header, command_lines, limit)
    command_page = max(0, min(command_page, len(pages) - 1))
    text = pages[command_page]
    if len(pages) > 1:
        text += f"\n\n<b>{html.escape(labels['page'])}: {command_page + 1}/{len(pages)}</b>"

    rows: List[List[Dict[str, str]]] = []
    navigation: List[Dict[str, str]] = []
    if command_page > 0:
        navigation.append(
            {"text": labels["previous"], "callback_data": f"zh{mode}:module:{module_index}:{command_page - 1}:{list_page}"}
        )
    if command_page + 1 < len(pages):
        navigation.append(
            {"text": labels["next"], "callback_data": f"zh{mode}:module:{module_index}:{command_page + 1}:{list_page}"}
        )
    if navigation:
        rows.append(navigation)
    rows.append(
        [
            {"text": labels["back"], "callback_data": f"zh{mode}:list:{list_page}"},
            {"text": labels["home"], "callback_data": f"zh{mode}:home"},
        ]
    )
    return text, _keyboard(rows)


async def _handle_inline_query(client: Any, inline_query: Any) -> None:
    query = str(getattr(inline_query, "query", "") or "")
    if not query.startswith("zelretch_help"):
        return
    try:
        await inline_query.answer(results=[_build_inline_result()], cache_time=0, is_personal=True)
    except Exception as exc:
        logging.warning("[InlineHelpBot] Could not answer inline query: %s", exc, exc_info=True)


async def _edit_text(callback_query: Any, text: str, markup: Any) -> None:
    from pyrogram.enums import ParseMode
    try:
        from pyrogram.types import LinkPreviewOptions
        await callback_query.edit_message_text(
            text=text[:4096],
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            reply_markup=markup,
        )
    except TypeError:
        await callback_query.edit_message_text(
            text=text[:4096],
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )


async def _handle_callback_query(client: Any, callback_query: Any) -> None:
    from pyrogram.enums import ParseMode

    raw_data = getattr(callback_query, "data", "") or ""
    if isinstance(raw_data, bytes):
        raw_data = raw_data.decode("utf-8", errors="replace")
    data = str(raw_data)
    if not data.startswith(("zhc:", "zht:")):
        return
    if not getattr(callback_query, "inline_message_id", None):
        await callback_query.answer(_labels()["unavailable"], show_alert=True)
        return

    mode = "c" if data.startswith("zhc:") else "t"
    parts = data.split(":")
    try:
        action = parts[1]
        if action == "home":
            text, markup = _help_caption(), _home_keyboard(mode)
        elif action == "list":
            text, markup = _list_view(mode, int(parts[2]) if len(parts) > 2 else 0)
        elif action == "module":
            text, markup = _module_view(
                mode,
                int(parts[2]),
                int(parts[3]),
                int(parts[4]),
            )
        else:
            await callback_query.answer()
            return

        if mode == "c":
            await callback_query.edit_message_caption(
                caption=text[:1024],
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        else:
            await _edit_text(callback_query, text, markup)
        await callback_query.answer()
    except Exception as exc:
        if "MESSAGE_NOT_MODIFIED" in str(exc).upper():
            try:
                await callback_query.answer()
            except Exception:
                pass
            return
        logging.warning("[InlineHelpBot] Callback handling failed: %s", exc, exc_info=True)
        try:
            await callback_query.answer(_labels()["unavailable"], show_alert=True)
        except Exception:
            pass


def create_inline_help_client(api_id: int, api_hash: str, bot_token: Optional[str] = None) -> Optional[Any]:
    global _bot_client

    token = str(bot_token or os.environ.get("BOT_TOKEN") or "").strip()
    if not token:
        logging.info("[InlineHelpBot] BOT_TOKEN is not configured; inline help is disabled")
        return None

    from pyrogram.client import Client
    from pyrogram.handlers import CallbackQueryHandler, InlineQueryHandler

    bot = Client(
        "zelretch_inline_help_bot",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=token,
        in_memory=True,
        device_model="Zelretch Command Center",
    )
    bot.add_handler(InlineQueryHandler(_handle_inline_query))
    bot.add_handler(CallbackQueryHandler(_handle_callback_query))
    _bot_client = bot
    return bot


async def mark_inline_help_bot_ready(client: Any) -> str:
    global _bot_username

    me = await client.get_me()
    username = str(getattr(me, "username", "") or "").strip().lstrip("@")
    if not username:
        raise RuntimeError("The BOT_TOKEN belongs to a bot without a username")
    _bot_username = username
    logging.info("[InlineHelpBot] Connected through Kurigram MTProto as @%s", username)
    return username


def clear_inline_help_bot_ready() -> None:
    global _bot_username, _bot_client
    _bot_client = None
    configured = (os.environ.get("INLINE_BOT_USERNAME") or "").strip().lstrip("@")
    _bot_username = configured or None


def get_inline_bot_username() -> Optional[str]:
    return _bot_username


async def send_inline_help(client: Any, message: Any) -> bool:
    username = get_inline_bot_username()
    if not username:
        for _ in range(10):
            await asyncio.sleep(0.2)
            username = get_inline_bot_username()
            if username:
                break
    if not username:
        logging.warning("[InlineHelpBot] Companion bot is not ready; using fallback help card")
        return False

    try:
        query = f"zelretch_help {time.time_ns()}"
        results = await client.get_inline_bot_results(username, query)
        available_results = getattr(results, "results", None)
        if not available_results:
            logging.warning(
                "[InlineHelpBot] @%s returned no inline result. Enable inline mode with /setinline in BotFather.",
                username,
            )
            return False
        await client.send_inline_bot_result(
            message.chat.id,
            results.query_id,
            available_results[0].id,
        )
        return True
    except Exception as exc:
        logging.warning(
            "[InlineHelpBot] Could not send inline help through @%s: %s",
            username,
            exc,
            exc_info=True,
        )
        return False
