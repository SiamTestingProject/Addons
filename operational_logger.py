# -*- coding: utf-8 -*-
"""Structured Telegram operational logging for Zelretch.

The configured or automatically provisioned companion bot is shared with the
inline-help service. Log events are queued until that bot connects, then sent to
the configured or automatically created logging channel. No token, channel ID,
or account identifier is hardcoded.
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

LOGGER = logging.getLogger(__name__)

_VALID_LEVELS = {"INFO", "WARNING", "ERROR", "CRITICAL"}
_LEVEL_NUMBERS = {
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
_LEVEL_ICONS = {
    "INFO": "ℹ️",
    "WARNING": "⚠️",
    "ERROR": "❌",
    "CRITICAL": "🚨",
}
_MAX_QUEUE_SIZE = 500
_MAX_CONTEXT_CHUNK = 2800
_RETRY_LIMIT = 3


def _env_flag(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}

_SECRET_PATTERNS = (
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b"), "<BOT_TOKEN_REDACTED>"),
    (
        re.compile(r"(mongodb(?:\+srv)?://)([^:@/\s]+):([^@/\s]+)@", re.IGNORECASE),
        r"\1<USERNAME_REDACTED>:<PASSWORD_REDACTED>@",
    ),
    (
        re.compile(
            r"(?i)\b(BOT_TOKEN|MONGODB_URI|API_HASH|PASSWORD|SECRET)\s*[=:]\s*([^\s,;]+)"
        ),
        r"\1=<REDACTED>",
    ),
)


@dataclass
class OperationalEvent:
    level: str
    event_type: str
    description: str
    error_details: str = ""
    technical_context: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attempts: int = 0


class OperationalLogService:
    def __init__(self) -> None:
        self.bot_token_configured = bool((os.environ.get("BOT_TOKEN") or "").strip())
        self.channel_raw = (os.environ.get("LOG_CHANNEL_ID") or "").strip()
        self.instance_id = (os.environ.get("FOX_INSTANCE_ID") or "default").strip() or "default"
        self.account_identifier = f"instance:{self.instance_id}"
        self._enabled = self.bot_token_configured and bool(self.channel_raw)
        self._auto_setup_pending = _env_flag("AUTO_TELEGRAM_SETUP", True)
        self._channel: Any = self._parse_channel(self.channel_raw)
        self._queue: "queue.Queue[OperationalEvent]" = queue.Queue(maxsize=_MAX_QUEUE_SIZE)
        self._client: Optional[Any] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._stop_requested = False
        self._inflight = 0
        self._root_handler: Optional[TelegramChannelLogHandler] = None
        self._expected_disconnect = False
        self._expected_disconnect_reason = ""
        self._recent: Dict[str, float] = {}
        self._recent_lock = threading.Lock()

    @staticmethod
    def _parse_channel(value: str) -> Any:
        if not value:
            return None
        normalized = value.strip()
        if re.fullmatch(r"-?\d+", normalized):
            try:
                return int(normalized)
            except ValueError:
                return normalized
        return normalized

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def ready(self) -> bool:
        return self._client is not None and self._worker_task is not None

    @property
    def expected_disconnect(self) -> bool:
        return self._expected_disconnect

    @property
    def expected_disconnect_reason(self) -> str:
        return self._expected_disconnect_reason

    def configure_from_environment(self) -> None:
        self.bot_token_configured = bool((os.environ.get("BOT_TOKEN") or "").strip())
        self.channel_raw = (os.environ.get("LOG_CHANNEL_ID") or "").strip()
        self._channel = self._parse_channel(self.channel_raw)
        self._enabled = self.bot_token_configured and bool(self.channel_raw)
        self._auto_setup_pending = _env_flag("AUTO_TELEGRAM_SETUP", True) and not self._enabled

    def set_account_identity(self, user: Any) -> None:
        user_id = getattr(user, "id", None)
        username = str(getattr(user, "username", "") or "").strip().lstrip("@")
        first_name = str(getattr(user, "first_name", "") or "").strip()
        pieces = []
        if username:
            pieces.append(f"@{username}")
        elif first_name:
            pieces.append(first_name)
        if user_id is not None:
            pieces.append(f"ID:{user_id}")
        pieces.append(f"instance:{self.instance_id}")
        self.account_identifier = " | ".join(pieces)

    def mark_expected_disconnect(self, reason: str) -> None:
        self._expected_disconnect = True
        self._expected_disconnect_reason = str(reason or "planned shutdown")

    def clear_expected_disconnect(self) -> None:
        self._expected_disconnect = False
        self._expected_disconnect_reason = ""

    def install_root_handler(self) -> None:
        if self._root_handler is not None:
            return
        self._root_handler = TelegramChannelLogHandler(self)
        self._root_handler.setLevel(logging.WARNING)
        logging.getLogger().addHandler(self._root_handler)

    def uninstall_root_handler(self) -> None:
        if self._root_handler is None:
            return
        try:
            logging.getLogger().removeHandler(self._root_handler)
        except Exception:
            pass
        self._root_handler = None

    def enqueue(self, event: OperationalEvent, deduplicate: bool = False) -> None:
        # Preserve startup/authentication events while automatic Telegram setup
        # is still creating the bot and channel. They are flushed as soon as the
        # generated BOT_TOKEN client binds to the service.
        if not self._enabled and not self._auto_setup_pending:
            return

        event.level = event.level.upper().strip()
        if event.level not in _VALID_LEVELS:
            event.level = "INFO"
        event.event_type = _normalize_event_type(event.event_type)
        event.description = _redact(str(event.description or "No description provided"))
        event.error_details = _redact(str(event.error_details or ""))
        event.technical_context = _redact(str(event.technical_context or ""))
        event.metadata = {
            str(key): _redact(str(value)) for key, value in (event.metadata or {}).items()
        }

        if deduplicate:
            fingerprint = "|".join(
                (event.level, event.event_type, event.description, event.error_details)
            )
            now = time.monotonic()
            with self._recent_lock:
                previous = self._recent.get(fingerprint)
                self._recent[fingerprint] = now
                stale = [key for key, timestamp in self._recent.items() if now - timestamp > 120]
                for key in stale:
                    self._recent.pop(key, None)
            if previous is not None and now - previous < 30:
                return

        try:
            self._queue.put_nowait(event)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                LOGGER.error("[LogChannel] Operational log queue is full; event dropped")

    async def bind_client(self, client: Any) -> None:
        self.configure_from_environment()
        if not self._enabled:
            if not self.channel_raw:
                LOGGER.info("[LogChannel] LOG_CHANNEL_ID is not configured; channel logging is disabled")
            elif not self.bot_token_configured:
                LOGGER.info("[LogChannel] BOT_TOKEN is not configured; channel logging is disabled")
            return
        self._client = client
        self._stop_requested = False
        await self._resolve_channel_peer()
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(
                self._worker(),
                name="zelretch-operational-log-worker",
            )
        self.enqueue(
            OperationalEvent(
                level="INFO",
                event_type="LOGGING_CHANNEL_READY",
                description="Operational logging bot connected and the channel delivery worker started.",
                metadata={"channel": self.channel_raw},
            )
        )


    async def _resolve_channel_peer(self) -> None:
        """Populate Kurigram's in-memory peer cache for private numeric channels."""
        if self._client is None or self._channel is None:
            return
        try:
            chat = await self._client.get_chat(self._channel)
            resolved_id = getattr(chat, "id", None)
            if resolved_id is not None:
                self._channel = resolved_id
            return
        except Exception as first_error:
            if not isinstance(self._channel, int):
                LOGGER.error(
                    "[LogChannel] Could not resolve LOG_CHANNEL_ID %s: %s",
                    self.channel_raw,
                    first_error,
                )
                return

        try:
            async for dialog in self._client.get_dialogs():
                chat = getattr(dialog, "chat", None)
                if getattr(chat, "id", None) == self._channel:
                    self._channel = chat.id
                    return
            LOGGER.error(
                "[LogChannel] LOG_CHANNEL_ID %s is not visible to the BOT_TOKEN bot. "
                "Add the bot as a channel administrator with permission to post messages.",
                self.channel_raw,
            )
        except Exception as second_error:
            LOGGER.error(
                "[LogChannel] Could not populate the bot peer cache for %s: %s",
                self.channel_raw,
                second_error,
            )

    async def _worker(self) -> None:
        while not self._stop_requested or not self._queue.empty():
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.25)
                continue

            self._inflight += 1
            try:
                await self._send_event(event)
            finally:
                self._inflight -= 1
                self._queue.task_done()

    async def _send_event(self, event: OperationalEvent) -> None:
        if self._client is None or self._channel is None:
            self._requeue(event)
            await asyncio.sleep(0.5)
            return

        try:
            for message in self._render_messages(event):
                await self._client.send_message(
                    self._channel,
                    message,
                    parse_mode=None,
                    disable_web_page_preview=True,
                )
        except asyncio.CancelledError:
            self._requeue(event)
            raise
        except Exception as exc:
            event.attempts += 1
            LOGGER.error(
                "[LogChannel] Delivery attempt %s/%s failed for %s: %s",
                event.attempts,
                _RETRY_LIMIT,
                event.event_type,
                exc,
            )
            if event.attempts < _RETRY_LIMIT and not self._stop_requested:
                await asyncio.sleep(min(2 ** event.attempts, 8))
                self._requeue(event)

    def _requeue(self, event: OperationalEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            LOGGER.error("[LogChannel] Could not requeue undelivered event: %s", event.event_type)

    def _render_messages(self, event: OperationalEvent) -> Iterable[str]:
        icon = _LEVEL_ICONS.get(event.level, "ℹ️")
        timestamp = event.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        lines = [
            f"{icon} {event.level} · {event.event_type}",
            f"Account: {_truncate(self.account_identifier, 500)}",
            f"Date and time: {timestamp}",
            f"Description: {_truncate(event.description, 1500)}",
        ]
        if event.error_details:
            lines.append(f"Error details: {_truncate(event.error_details, 1200)}")
        if event.metadata:
            lines.append("Context:")
            for key, value in sorted(event.metadata.items()):
                lines.append(f"- {_truncate(key, 100)}: {_truncate(value, 500)}")
        if event.technical_context.strip():
            lines.extend(("Technical context:", event.technical_context.strip()))

        full_text = "\n".join(lines)
        chunks = list(_split_plain_text(full_text, 3900))
        for index, chunk in enumerate(chunks):
            if index == 0:
                yield chunk
            else:
                prefix = f"{icon} {event.level} · {event.event_type} (continued {index + 1}/{len(chunks)})\n"
                available = 4090 - len(prefix)
                yield prefix + chunk[:available]

    async def drain(self, timeout: float = 5.0) -> bool:
        if not self._enabled or self._worker_task is None:
            return True
        deadline = asyncio.get_running_loop().time() + max(0.1, timeout)
        while (not self._queue.empty() or self._inflight) and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.1)
        return self._queue.empty() and self._inflight == 0

    async def shutdown(self, timeout: float = 5.0) -> None:
        if self._worker_task is None:
            self._client = None
            return
        await self.drain(timeout=timeout)
        self._stop_requested = True
        try:
            await asyncio.wait_for(self._worker_task, timeout=max(0.5, timeout))
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._worker_task = None
        self._client = None


class TelegramChannelLogHandler(logging.Handler):
    """Forward ordinary WARNING/ERROR/CRITICAL records as structured events."""

    def __init__(self, service: OperationalLogService) -> None:
        super().__init__(level=logging.WARNING)
        self.service = service

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.name == __name__ or record.name.startswith(f"{__name__}."):
                return
            message = record.getMessage()
            if message.startswith("[LogChannel]"):
                return
            level = _level_name(record.levelno)
            technical_context = ""
            if record.exc_info:
                technical_context = "".join(traceback.format_exception(*record.exc_info))
            elif record.stack_info:
                technical_context = str(record.stack_info)
            self.service.enqueue(
                OperationalEvent(
                    level=level,
                    event_type=_classify_log_record(record, message),
                    description=message,
                    technical_context=technical_context,
                    metadata={
                        "logger": record.name,
                        "source": f"{record.pathname}:{record.lineno}",
                        "thread": record.threadName,
                    },
                ),
                deduplicate=True,
            )
        except Exception:
            self.handleError(record)


_SERVICE = OperationalLogService()
_ORIGINAL_SYS_EXCEPTHOOK = sys.excepthook
_ORIGINAL_THREADING_EXCEPTHOOK = getattr(threading, "excepthook", None)
_HOOKS_INSTALLED = False


def get_operational_logger() -> OperationalLogService:
    return _SERVICE


def configure_operational_logging() -> OperationalLogService:
    _SERVICE.configure_from_environment()
    _SERVICE.install_root_handler()
    install_exception_hooks()
    return _SERVICE


def report_event(
    level: str,
    event_type: str,
    description: str,
    *,
    error_details: str = "",
    technical_context: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    _SERVICE.enqueue(
        OperationalEvent(
            level=level,
            event_type=event_type,
            description=description,
            error_details=error_details,
            technical_context=technical_context,
            metadata=metadata or {},
        )
    )


def report_exception(
    level: str,
    event_type: str,
    description: str,
    exception: BaseException,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    context = "".join(
        traceback.format_exception(type(exception), exception, exception.__traceback__)
    )
    report_event(
        level,
        event_type,
        description,
        error_details=f"{type(exception).__name__}: {exception}",
        technical_context=context,
        metadata=metadata,
    )


async def bind_log_bot(client: Any) -> None:
    await _SERVICE.bind_client(client)


async def flush_operational_logs(timeout: float = 5.0) -> bool:
    return await _SERVICE.drain(timeout)


async def shutdown_operational_logging(timeout: float = 5.0) -> None:
    await _SERVICE.shutdown(timeout)


def set_account_identity(user: Any) -> None:
    _SERVICE.set_account_identity(user)


def mark_expected_disconnect(reason: str) -> None:
    _SERVICE.mark_expected_disconnect(reason)


def clear_expected_disconnect() -> None:
    _SERVICE.clear_expected_disconnect()


def install_asyncio_exception_handler(loop: asyncio.AbstractEventLoop) -> None:
    previous_handler = loop.get_exception_handler()

    def handler(active_loop: asyncio.AbstractEventLoop, context: Dict[str, Any]) -> None:
        exception = context.get("exception")
        message = str(context.get("message") or "Unhandled asyncio task exception")
        metadata = {
            key: repr(value)
            for key, value in context.items()
            if key not in {"exception", "message"}
        }
        if isinstance(exception, BaseException):
            report_exception(
                "ERROR",
                "BACKGROUND_TASK_FAILURE",
                message,
                exception,
                metadata=metadata,
            )
        else:
            report_event(
                "ERROR",
                "BACKGROUND_TASK_FAILURE",
                message,
                technical_context=repr(context),
                metadata=metadata,
            )

        if previous_handler is not None:
            previous_handler(active_loop, context)
        else:
            active_loop.default_exception_handler(context)

    loop.set_exception_handler(handler)


def wrap_message_handler(handler: Any, group: Any = "dynamic") -> bool:
    """Wrap one Kurigram MessageHandler callback with structured error reporting."""
    if handler.__class__.__name__ != "MessageHandler":
        return False
    if getattr(handler, "_zelretch_operational_logging_wrapped", False):
        return False
    original = getattr(handler, "callback", None)
    if original is None:
        return False

    async def guarded_callback(
        active_client: Any,
        message: Any,
        *args: Any,
        __original: Any = original,
        __group: Any = group,
        **kwargs: Any,
    ) -> Any:
        try:
            result = __original(active_client, message, *args, **kwargs)
            if asyncio.iscoroutine(result):
                return await result
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            text = str(
                getattr(message, "text", None)
                or getattr(message, "caption", None)
                or ""
            )
            chat = getattr(message, "chat", None)
            sender = getattr(message, "from_user", None)
            report_exception(
                "ERROR",
                "COMMAND_PROCESSING_ERROR",
                "A command or message handler raised an unhandled exception.",
                exc,
                metadata={
                    "handler": getattr(__original, "__qualname__", repr(__original)),
                    "module": getattr(__original, "__module__", "unknown"),
                    "dispatcher_group": __group,
                    "chat_id": getattr(chat, "id", "unknown"),
                    "message_id": getattr(message, "id", "unknown"),
                    "sender_id": getattr(sender, "id", "unknown"),
                    "message_text": text[:500],
                },
            )
            raise

    handler.callback = guarded_callback
    handler._zelretch_operational_logging_wrapped = True
    return True


def install_command_error_guard(client: Any) -> int:
    """Wrap all currently registered message callbacks with error reporting."""
    wrapped = 0
    groups = getattr(getattr(client, "dispatcher", None), "groups", {}) or {}
    for group, handlers in list(groups.items()):
        for handler in list(handlers):
            if wrap_message_handler(handler, group):
                wrapped += 1
    return wrapped


def install_exception_hooks() -> None:
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return

    def sys_hook(exc_type: Any, exc_value: BaseException, exc_traceback: Any) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            _ORIGINAL_SYS_EXCEPTHOOK(exc_type, exc_value, exc_traceback)
            return
        context = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        report_event(
            "CRITICAL",
            "UNHANDLED_EXCEPTION",
            "An unhandled exception reached the process-level exception hook.",
            error_details=f"{exc_type.__name__}: {exc_value}",
            technical_context=context,
        )
        _ORIGINAL_SYS_EXCEPTHOOK(exc_type, exc_value, exc_traceback)

    sys.excepthook = sys_hook

    if _ORIGINAL_THREADING_EXCEPTHOOK is not None:
        def thread_hook(args: Any) -> None:
            context = "".join(
                traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
            )
            report_event(
                "ERROR",
                "BACKGROUND_TASK_FAILURE",
                "An unhandled exception terminated a background thread.",
                error_details=f"{args.exc_type.__name__}: {args.exc_value}",
                technical_context=context,
                metadata={"thread": getattr(args.thread, "name", "unknown")},
            )
            _ORIGINAL_THREADING_EXCEPTHOOK(args)

        threading.excepthook = thread_hook

    _HOOKS_INSTALLED = True


def _normalize_event_type(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "EVENT")).strip("_")
    return normalized.upper() or "EVENT"


def _level_name(level_number: int) -> str:
    if level_number >= logging.CRITICAL:
        return "CRITICAL"
    if level_number >= logging.ERROR:
        return "ERROR"
    if level_number >= logging.WARNING:
        return "WARNING"
    return "INFO"


def _classify_log_record(record: logging.LogRecord, message: str) -> str:
    lowered = message.lower()
    if "mongodb" in lowered and any(token in lowered for token in ("sync", "background", "periodic")):
        return "BACKGROUND_TASK_FAILURE" if record.levelno >= logging.ERROR else "IMPORTANT_WARNING"
    if any(token in lowered for token in ("rpc error", "api error", "floodwait", "flood wait")):
        return "API_ERROR"
    if "inlinehelpbot" in lowered and any(
        token in lowered for token in ("failed", "unable", "could not", "error")
    ):
        return "API_ERROR"
    if any(token in lowered for token in ("auth", "session", "password", "phone code")):
        return "AUTHENTICATION_ERROR"
    if any(token in lowered for token in ("connect", "network", "disconnect", "timeout", "handshake")):
        return "CONNECTION_FAILURE" if record.levelno >= logging.ERROR else "IMPORTANT_WARNING"
    if "plugin" in lowered or "handler" in lowered or "command" in lowered:
        return "COMMAND_PROCESSING_ERROR" if record.levelno >= logging.ERROR else "IMPORTANT_WARNING"
    if record.exc_info:
        return "UNHANDLED_EXCEPTION"
    if record.levelno >= logging.CRITICAL:
        return "CRITICAL_SYSTEM_EVENT"
    if record.levelno >= logging.ERROR:
        return "SYSTEM_ERROR"
    return "IMPORTANT_WARNING"


def _truncate(value: Any, limit: int) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _split_plain_text(value: str, limit: int) -> Iterable[str]:
    """Split a Telegram message without dropping stack-trace content."""
    current = ""
    for line in value.splitlines() or [""]:
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            yield current
            current = ""
        while len(line) > limit:
            yield line[:limit]
            line = line[limit:]
        current = line
    if current:
        yield current


def _redact(value: str) -> str:
    result = value
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result
