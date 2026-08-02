# -*- coding: utf-8 -*-
"""Automatic Telegram service-bot and logging-channel bootstrap.

Environment variables always take priority. When BOT_TOKEN or LOG_CHANNEL_ID is
missing, the authorized Zelretch user account creates the missing resource and
stores the generated settings in MongoDB for subsequent deployments.

Bot creation is performed through the official @BotFather conversation because
Telegram does not expose a general unaffiliated-bot creation endpoint. The flow
is deliberately idempotent: MongoDB values are reused before any new resource is
created.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

LOGGER = logging.getLogger(__name__)
BOTFATHER = "BotFather"
TOKEN_RE = re.compile(r"\b(\d{6,12}:[A-Za-z0-9_-]{20,})\b")


class TelegramBootstrapError(RuntimeError):
    """Raised when automatic Telegram resource provisioning cannot complete."""


@dataclass(frozen=True)
class TelegramServiceSettings:
    bot_token: str
    bot_username: str
    log_channel_id: str
    bot_source: str
    channel_source: str


def _env_flag(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _message_text(message: Any) -> str:
    return str(
        getattr(message, "text", None)
        or getattr(message, "caption", None)
        or ""
    )


async def _wait_for_botfather_reply(
    client: Any,
    after_message_id: int,
    *,
    timeout: float = 45.0,
) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = []
        async for message in client.get_chat_history(BOTFATHER, limit=12):
            message_id = int(getattr(message, "id", 0) or 0)
            if message_id <= after_message_id or bool(getattr(message, "outgoing", False)):
                continue
            candidates.append(message)
        if candidates:
            return min(candidates, key=lambda item: int(getattr(item, "id", 0) or 0))
        await asyncio.sleep(0.75)
    raise TelegramBootstrapError(
        f"Timed out waiting for @{BOTFATHER}. Telegram may be rate-limiting the account."
    )


async def _botfather_exchange(
    client: Any,
    text: str,
    *,
    timeout: float = 45.0,
) -> Any:
    sent = await client.send_message(BOTFATHER, text)
    return await _wait_for_botfather_reply(
        client,
        int(getattr(sent, "id", 0) or 0),
        timeout=timeout,
    )


def _bot_display_name() -> str:
    configured = (os.environ.get("AUTO_BOT_NAME") or "Zelretch Service").strip()
    return (configured or "Zelretch Service")[:64]


def _bot_username(instance_id: str, account_id: Any, attempt: int) -> str:
    prefix = re.sub(
        r"[^A-Za-z0-9_]",
        "",
        (os.environ.get("AUTO_BOT_USERNAME_PREFIX") or "Zelretch").strip(),
    )
    prefix = prefix[:14] or "Zelretch"
    seed = f"{instance_id}:{account_id}:{attempt}:{secrets.token_hex(5)}".encode("utf-8")
    digest = hashlib.sha256(seed).hexdigest()[:10]
    username = f"{prefix}_{digest}Bot"
    return username[:32]


async def _create_bot_via_botfather(
    client: Any,
    *,
    instance_id: str,
    account_id: Any,
) -> Tuple[str, str]:
    LOGGER.warning(
        "[TelegramBootstrap] BOT_TOKEN is absent; creating a dedicated service bot through @BotFather"
    )

    # Reset any unfinished BotFather wizard left by an earlier interrupted
    # deployment before starting a new creation flow.
    try:
        await _botfather_exchange(client, "/cancel", timeout=15.0)
    except Exception:
        pass

    first_reply = await _botfather_exchange(client, "/newbot")
    first_text = _message_text(first_reply).lower()
    if any(marker in first_text for marker in ("too many bots", "bot create limit", "cannot create")):
        raise TelegramBootstrapError(
            "@BotFather refused to create another bot because the Telegram account has reached its bot limit."
        )

    await _botfather_exchange(client, _bot_display_name())

    for attempt in range(1, 9):
        username = _bot_username(instance_id, account_id, attempt)
        reply = await _botfather_exchange(client, username)
        text = _message_text(reply)
        token_match = TOKEN_RE.search(text)
        if token_match:
            token = token_match.group(1)
            LOGGER.info("[TelegramBootstrap] Created service bot @%s", username)
            await _enable_inline_mode(client, username)
            return token, username

        lowered = text.lower()
        if any(
            marker in lowered
            for marker in (
                "already taken",
                "username is invalid",
                "sorry, this username",
                "must end in",
                "choose a different",
            )
        ):
            continue

        if any(marker in lowered for marker in ("too many bots", "bot create limit", "cannot create")):
            raise TelegramBootstrapError(
                "@BotFather refused to create another bot because the Telegram account has reached its bot limit."
            )

        # BotFather occasionally sends an informational message before the token.
        try:
            follow_up = await _wait_for_botfather_reply(
                client,
                int(getattr(reply, "id", 0) or 0),
                timeout=8.0,
            )
            token_match = TOKEN_RE.search(_message_text(follow_up))
            if token_match:
                token = token_match.group(1)
                LOGGER.info("[TelegramBootstrap] Created service bot @%s", username)
                await _enable_inline_mode(client, username)
                return token, username
        except TelegramBootstrapError:
            pass

    raise TelegramBootstrapError(
        "@BotFather did not provide a bot token after several unique username attempts."
    )


async def _enable_inline_mode(client: Any, username: str) -> None:
    """Enable inline mode for the generated companion bot through BotFather."""
    placeholder = (
        os.environ.get("AUTO_INLINE_PLACEHOLDER")
        or "Search Zelretch commands"
    ).strip()[:64]
    try:
        await _botfather_exchange(client, "/setinline")
        await _botfather_exchange(client, f"@{username}")
        final_reply = await _botfather_exchange(client, placeholder)
        final_text = _message_text(final_reply).lower()
        if "inline" not in final_text and "success" not in final_text and "enabled" not in final_text:
            LOGGER.warning(
                "[TelegramBootstrap] BotFather did not clearly confirm inline mode for @%s",
                username,
            )
        else:
            LOGGER.info("[TelegramBootstrap] Inline mode enabled for @%s", username)
    except Exception as exc:
        # Logging still works without inline mode. Preserve startup and surface a
        # warning so the operator can use /setinline manually if Telegram changes
        # the BotFather conversation flow.
        LOGGER.warning(
            "[TelegramBootstrap] Could not enable inline mode automatically for @%s: %s",
            username,
            exc,
            exc_info=True,
        )


async def _resolve_bot_username(
    client: Any,
    token: str,
    stored_username: str,
    *,
    api_id: int,
    api_hash: str,
) -> str:
    """Validate BOT_TOKEN and resolve the bot username through MTProto."""
    from pyrogram.client import Client

    probe = Client(
        "zelretch_service_bot_probe",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=token,
        in_memory=True,
        device_model="Zelretch Service Bootstrap",
    )
    last_error: Optional[BaseException] = None
    try:
        for attempt in range(1, 4):
            try:
                await probe.start()
                bot = await probe.get_me()
                username = str(getattr(bot, "username", "") or "").strip().lstrip("@")
                if not username:
                    raise TelegramBootstrapError("The service bot has no Telegram username.")
                return username
            except TelegramBootstrapError:
                raise
            except Exception as exc:
                last_error = exc
                try:
                    await probe.stop()
                except Exception:
                    pass
                if attempt < 3:
                    await asyncio.sleep(attempt * 2)
        source_hint = f"@{stored_username}" if stored_username else "the supplied token"
        raise TelegramBootstrapError(
            f"The BOT_TOKEN for {source_hint} could not authorize a Telegram bot."
        ) from last_error
    finally:
        try:
            await probe.stop()
        except Exception:
            pass


async def _ensure_bot_channel_admin(
    client: Any,
    *,
    channel_id: Any,
    bot_username: str,
) -> None:
    from pyrogram.types import ChatPrivileges

    bot = await client.get_users(bot_username)
    bot_id = int(getattr(bot, "id"))

    try:
        await client.add_chat_members(channel_id, bot_id)
    except Exception as exc:
        normalized = str(exc).upper()
        if not any(
            marker in normalized
            for marker in (
                "USER_ALREADY_PARTICIPANT",
                "USER_ALREADY_MEMBER",
                "CHAT_ADMIN_REQUIRED",  # promotion below will provide clearer context
            )
        ):
            LOGGER.info(
                "[TelegramBootstrap] Bot membership add returned %s; attempting direct promotion",
                exc,
            )

    privileges = ChatPrivileges(
        can_manage_chat=True,
        can_post_messages=True,
        can_edit_messages=True,
    )
    await client.promote_chat_member(channel_id, bot_id, privileges=privileges)
    LOGGER.info(
        "[TelegramBootstrap] @%s is an administrator of logging channel %s",
        bot_username,
        channel_id,
    )


def _normalize_channel_id(value: Any) -> str:
    return str(value or "").strip()


async def _create_logging_channel(client: Any) -> Any:
    title = (
        os.environ.get("AUTO_LOG_CHANNEL_TITLE")
        or "Zelretch Operational Logs"
    ).strip()[:128]
    description = (
        os.environ.get("AUTO_LOG_CHANNEL_DESCRIPTION")
        or "Automatically created private channel for Zelretch operational logs."
    ).strip()[:255]
    channel = await client.create_channel(title, description)
    LOGGER.info(
        "[TelegramBootstrap] Created private logging channel %s (%s)",
        getattr(channel, "title", title),
        getattr(channel, "id", "unknown"),
    )
    return channel


async def bootstrap_telegram_services(
    user_client: Any,
    storage: Any,
    *,
    api_id: int,
    api_hash: str,
) -> TelegramServiceSettings:
    """Resolve or provision BOT_TOKEN and LOG_CHANNEL_ID.

    Priority order:
      1. Explicit environment variables.
      2. Values previously persisted in MongoDB.
      3. Automatic creation through the authorized Telegram user account.
    """
    auto_setup = _env_flag("AUTO_TELEGRAM_SETUP", True)
    persisted: Dict[str, Any] = storage.get_telegram_service_config()
    me = await user_client.get_me()

    env_token = (os.environ.get("BOT_TOKEN") or "").strip()
    stored_token = str(persisted.get("bot_token") or "").strip()
    stored_username = str(persisted.get("bot_username") or "").strip().lstrip("@")

    if env_token:
        bot_token = env_token
        bot_source = "environment"
    elif stored_token:
        bot_token = stored_token
        bot_source = "mongodb"
    elif auto_setup:
        bot_token, stored_username = await _create_bot_via_botfather(
            user_client,
            instance_id=storage.instance_id,
            account_id=getattr(me, "id", "unknown"),
        )
        bot_source = "automatic"
    else:
        raise TelegramBootstrapError(
            "BOT_TOKEN is missing and AUTO_TELEGRAM_SETUP is disabled."
        )

    bot_username = await _resolve_bot_username(
        user_client,
        bot_token,
        stored_username,
        api_id=api_id,
        api_hash=api_hash,
    )
    storage.save_telegram_service_bot(
        bot_token=bot_token,
        bot_username=bot_username,
        bot_id=bot_token.split(":", 1)[0],
        source=bot_source,
    )
    os.environ["BOT_TOKEN"] = bot_token
    os.environ["INLINE_BOT_USERNAME"] = bot_username

    env_channel = (os.environ.get("LOG_CHANNEL_ID") or "").strip()
    stored_channel = _normalize_channel_id(persisted.get("log_channel_id"))
    channel_source = ""
    channel: Optional[Any] = None

    if env_channel:
        channel_id = env_channel
        channel_source = "environment"
        channel = await user_client.get_chat(int(env_channel) if re.fullmatch(r"-?\d+", env_channel) else env_channel)
    elif stored_channel:
        channel_id = stored_channel
        channel_source = "mongodb"
        try:
            channel = await user_client.get_chat(
                int(stored_channel) if re.fullmatch(r"-?\d+", stored_channel) else stored_channel
            )
        except Exception as exc:
            if not auto_setup:
                raise TelegramBootstrapError(
                    "The logging channel stored in MongoDB is unavailable and automatic setup is disabled."
                ) from exc
            LOGGER.warning(
                "[TelegramBootstrap] Stored logging channel is unavailable; creating a replacement: %s",
                exc,
            )
            channel = await _create_logging_channel(user_client)
            channel_id = str(getattr(channel, "id"))
            channel_source = "automatic_replacement"
    elif auto_setup:
        channel = await _create_logging_channel(user_client)
        channel_id = str(getattr(channel, "id"))
        channel_source = "automatic"
    else:
        raise TelegramBootstrapError(
            "LOG_CHANNEL_ID is missing and AUTO_TELEGRAM_SETUP is disabled."
        )

    resolved_channel_id = str(getattr(channel, "id", channel_id))

    # Persist the channel before promotion. If Telegram temporarily rejects the
    # admin update, the next deployment reuses this channel instead of creating
    # a duplicate and retries the promotion.
    storage.save_telegram_log_channel(
        channel_id=resolved_channel_id,
        title=str(getattr(channel, "title", "") or ""),
        source=channel_source,
    )
    os.environ["LOG_CHANNEL_ID"] = resolved_channel_id

    await _ensure_bot_channel_admin(
        user_client,
        channel_id=(
            int(resolved_channel_id)
            if re.fullmatch(r"-?\d+", resolved_channel_id)
            else resolved_channel_id
        ),
        bot_username=bot_username,
    )

    return TelegramServiceSettings(
        bot_token=bot_token,
        bot_username=bot_username,
        log_channel_id=resolved_channel_id,
        bot_source=bot_source,
        channel_source=channel_source,
    )
