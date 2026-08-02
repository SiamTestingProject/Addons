# -*- coding: utf-8 -*-
import logging
import os
import sys

import pip

from migrate import convert_modules
from requirements_installer import install_library

logger = logging.getLogger(__name__)


def is_running_in_termux():
    termux_vars = [
        "TERMUX_VERSION",
        "TERMUX_APK_RELEASE",
        "PREFIX",
    ]
    return any(var in os.environ for var in termux_vars)


def check_structure():
    if os.path.exists("localhost_run_output.txt"):
        os.remove("localhost_run_output.txt")
    for directory in (
        "temp",
        "userdata",
        "triggers",
        "modules/loaded",
        "broken_modules",
    ):
        os.makedirs(directory, exist_ok=True)


def autoupdater():
    try:
        from pyrogram.client import Client  # noqa: F401
    except ImportError:
        try:
            os.remove("temp/firstlaunch.temp")
        except OSError:
            pass

    first_launched = False
    try:
        with open("temp/firstlaunch.temp", "r", encoding="utf-8") as file:
            first_launched = file.readline().strip() == "1"
    except FileNotFoundError:
        pass

    if not first_launched:
        pip.main(["uninstall", "pyrogram", "kurigram", "-y"])

        try:
            if not is_running_in_termux():
                install_library("uv -U")
            else:
                os.system("termux-wake-lock")
                os.system("pkg update -y ; pkg install uv -y")
        except Exception as exc:
            logger.warning(exc)

        try:
            install_library("tgcrypto -U")
        except Exception as exc:
            logger.warning(exc)

        with open("temp/firstlaunch.temp", "w", encoding="utf-8") as file:
            file.write("1")

    install_library("-r requirements.txt -U")
    setup_logging()
    logger.info("Logging restored after installing dependencies")


def setup_logging():
    safe_mode = "--safe" in sys.argv
    log_file = "temp/zelretch_safe.log" if safe_mode else "temp/zelretch.log"
    try:
        if os.path.exists(log_file):
            os.remove(log_file)
    except OSError:
        pass

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.INFO)
    return root_logger


async def authorize_cli(api_id, api_hash, device_model, storage):
    from pyrogram.client import Client

    client = Client(
        "zelretch_cli_auth",
        api_id=api_id,
        api_hash=api_hash,
        device_model=device_model,
        in_memory=True,
    )
    await client.start()
    try:
        user = await client.get_me()
        session_string = await client.export_session_string()
        storage.save_session_string(session_string)
        return user
    finally:
        await client.stop()


def run_zelretch(storage):
    import asyncio

    from pyrogram.client import Client
    from pyrogram.handlers import DisconnectHandler

    from configurator import my_api
    from operational_logger import (
        bind_log_bot,
        clear_expected_disconnect,
        flush_operational_logs,
        get_operational_logger,
        install_asyncio_exception_handler,
        install_command_error_guard,
        mark_expected_disconnect,
        report_event,
        report_exception,
        set_account_identity,
        shutdown_operational_logging,
    )
    from prestarter import prestart
    from web_auth.web_auth import start_web_auth

    safe_mode = "--safe" in sys.argv
    if safe_mode:
        logger.warning("[Zelretch] Starting in safe mode (only core modules)...")
        report_event(
            "WARNING",
            "SAFE_MODE_STARTUP",
            "Zelretch is starting in safe mode with only core modules enabled.",
        )

    api_id, api_hash, device_mod = my_api()
    newly_authorized = False
    try:
        session_string = storage.get_session_string()
    except Exception as exc:
        report_exception(
            "CRITICAL",
            "SESSION_ERROR",
            "The Telegram session could not be read from MongoDB.",
            exc,
        )
        raise

    if not session_string:
        logger.warning("[Zelretch] First launch for this MongoDB instance; authorization required...")
        report_event(
            "WARNING",
            "AUTHORIZATION_REQUIRED",
            "No Telegram session exists for this MongoDB instance. Interactive authorization is required once.",
        )
        try:
            if "--cli" in sys.argv:
                logger.info("[Zelretch] Running authorization in CLI mode...")
                user = asyncio.run(authorize_cli(api_id, api_hash, device_mod, storage))
                if user is None:
                    raise RuntimeError("CLI authorization returned no Telegram account")
            else:
                success, user = start_web_auth(api_id, api_hash, device_mod)
                if not success or user is None:
                    logger.warning("[Zelretch] Authorization failed")
                    report_event(
                        "ERROR",
                        "AUTHENTICATION_ERROR",
                        "Telegram authorization did not complete successfully.",
                    )
                    return
            newly_authorized = True
            set_account_identity(user)
        except Exception as exc:
            report_exception(
                "CRITICAL",
                "AUTHENTICATION_ERROR",
                "Telegram authorization failed.",
                exc,
            )
            raise

        session_string = storage.get_session_string()
        if not session_string:
            exc = RuntimeError("Authorization completed without saving a MongoDB session")
            report_exception(
                "CRITICAL",
                "SESSION_ERROR",
                "Authorization completed but no session string was saved in MongoDB.",
                exc,
            )
            raise exc
        logger.info("[Zelretch] Telegram session stored in MongoDB")
        report_event(
            "INFO",
            "AUTHORIZATION_SUCCESS",
            "Telegram authorization succeeded and the session was stored in MongoDB.",
        )
    else:
        logger.info("[Zelretch] Telegram session restored from MongoDB; authorization not required")
        report_event(
            "INFO",
            "SESSION_RESTORED",
            "The Telegram session was restored from MongoDB; no new authorization was required.",
        )

    try:
        prestart(api_id, api_hash, device_mod, session_string)
    except Exception as exc:
        report_exception(
            "ERROR",
            "CONNECTION_FAILURE",
            "The pre-start Telegram connection check failed.",
            exc,
        )
        raise

    try:
        client = Client(
            "my_account",
            api_id=api_id,
            api_hash=api_hash,
            device_model=device_mod,
            session_string=session_string,
            in_memory=True,
            plugins=dict(root="modules/core"),
        )

        @client.on_start()
        async def load_external_plugins_on_start(client):
            if not safe_mode:
                from modules.core.plugin_loader import load_all_external_addons
                from modules.core.plugin_validator import PluginValidator

                validator = PluginValidator()
                logging.info("[Zelretch] Validating existing addons...")
                validator.validate_existing_plugins()
                load_all_external_addons(client)
                logger.info("[Zelretch] Addons loaded successfully")

        async def disconnect_observer(active_client, *args):
            service = get_operational_logger()
            if service.expected_disconnect:
                return
            report_event(
                "WARNING",
                "UNEXPECTED_DISCONNECTION",
                "The Zelretch Telegram client disconnected without a planned shutdown marker.",
                metadata={"client": "my_account"},
            )

        client.add_handler(DisconnectHandler(disconnect_observer), group=-1000)

        async def run_clients():
            from pyrogram import idle
            from inline_help_bot import (
                clear_inline_help_bot_ready,
                create_inline_help_client,
                mark_inline_help_bot_ready,
            )
            from telegram_bootstrap import bootstrap_telegram_services

            install_asyncio_exception_handler(asyncio.get_running_loop())
            user_started = False
            inline_bot = None
            inline_bot_started = False
            runtime_exception = None
            service_settings = None
            try:
                # The authorized user account starts first because it is the only
                # identity allowed to create a missing bot/channel and promote the
                # bot. Startup events remain queued until the bot is ready.
                try:
                    clear_expected_disconnect()
                    await client.start()
                    user_started = True
                    account = await client.get_me()
                    set_account_identity(account)
                    wrapped_handlers = install_command_error_guard(client)
                    report_event(
                        "INFO",
                        "CONNECTION_SUCCESS",
                        "Zelretch connected to Telegram and started processing updates.",
                        metadata={
                            "authorized_now": newly_authorized,
                            "safe_mode": safe_mode,
                            "guarded_handlers": wrapped_handlers,
                        },
                    )
                except Exception as exc:
                    report_exception(
                        "CRITICAL",
                        "CONNECTION_FAILURE",
                        "Zelretch could not connect the authorized user account to Telegram.",
                        exc,
                    )
                    await flush_operational_logs(5.0)
                    raise

                try:
                    service_settings = await bootstrap_telegram_services(
                        client, storage, api_id=api_id, api_hash=api_hash
                    )
                    report_event(
                        "INFO",
                        "TELEGRAM_SERVICE_BOOTSTRAP_COMPLETE",
                        "The companion bot and operational logging channel are configured.",
                        metadata={
                            "bot_username": f"@{service_settings.bot_username}",
                            "bot_source": service_settings.bot_source,
                            "log_channel_id": service_settings.log_channel_id,
                            "channel_source": service_settings.channel_source,
                        },
                    )
                except Exception as exc:
                    # The primary Zelretch runtime remains usable when Telegram refuses
                    # resource creation. The error is retained locally and will be
                    # delivered later if a usable configured bot still exists.
                    logger.error(
                        "[TelegramBootstrap] Automatic setup failed: %s",
                        exc,
                        exc_info=True,
                    )
                    report_exception(
                        "ERROR",
                        "TELEGRAM_SERVICE_BOOTSTRAP_FAILURE",
                        "Automatic companion-bot or logging-channel setup failed.",
                        exc,
                    )

                inline_bot = create_inline_help_client(
                    api_id,
                    api_hash,
                    bot_token=(
                        service_settings.bot_token
                        if service_settings is not None
                        else os.environ.get("BOT_TOKEN")
                    ),
                )
                if inline_bot is not None:
                    last_error = None
                    for attempt in range(1, 4):
                        try:
                            await inline_bot.start()
                            inline_bot_started = True
                            await mark_inline_help_bot_ready(inline_bot)
                            await bind_log_bot(inline_bot)
                            break
                        except Exception as exc:
                            last_error = exc
                            logger.warning(
                                "[InlineHelpBot] MTProto startup attempt %s/3 failed: %s",
                                attempt,
                                exc,
                                exc_info=True,
                            )
                            if inline_bot_started:
                                try:
                                    await inline_bot.stop()
                                except Exception:
                                    pass
                                inline_bot_started = False
                            if attempt < 3:
                                await asyncio.sleep(attempt * 3)
                    if not inline_bot_started:
                        logger.warning(
                            "[InlineHelpBot] Disabled after MTProto startup failures: %s",
                            last_error,
                        )

                report_event(
                    "INFO",
                    "ZELRETCH_STARTUP_COMPLETE",
                    "Zelretch startup completed successfully.",
                    metadata={
                        "safe_mode": safe_mode,
                        "inline_bot_started": inline_bot_started,
                        "automatic_telegram_setup": service_settings is not None,
                    },
                )
                await idle()
            except Exception as exc:
                runtime_exception = exc
                report_exception(
                    "CRITICAL",
                    "CRITICAL_SYSTEM_EVENT",
                    "The primary Zelretch runtime stopped because of an exception.",
                    exc,
                )
                await flush_operational_logs(5.0)
                raise
            finally:
                shutdown_reason = (
                    "runtime exception" if runtime_exception is not None else "shutdown signal or idle loop termination"
                )
                mark_expected_disconnect(shutdown_reason)
                report_event(
                    "INFO" if runtime_exception is None else "CRITICAL",
                    "ZELRETCH_SHUTDOWN",
                    "Zelretch is shutting down.",
                    error_details=str(runtime_exception or ""),
                    metadata={"reason": shutdown_reason},
                )

                if user_started:
                    try:
                        await client.stop()
                    except Exception as exc:
                        report_exception(
                            "ERROR",
                            "SHUTDOWN_ERROR",
                            "The Telegram user client failed to stop cleanly.",
                            exc,
                        )

                if inline_bot_started and inline_bot is not None:
                    try:
                        await flush_operational_logs(5.0)
                        await shutdown_operational_logging(5.0)
                    except Exception as exc:
                        logger.warning("[LogChannel] Shutdown flush failed: %s", exc)
                    try:
                        await inline_bot.stop()
                    except Exception as exc:
                        logger.warning("[InlineHelpBot] Stop failed: %s", exc)
                clear_inline_help_bot_ready()

        # Kurigram 2.2.x exposes Client.run() as a zero-argument convenience
        # method. Passing a coroutine to it raises ``TypeError: Run.run() takes
        # 1 positional argument but 2 were given`` and leaves the coroutine
        # unawaited. Execute the multi-client coroutine on the same event loop
        # captured by the Kurigram client instead of creating a different loop.
        runtime_loop = getattr(client, "loop", None)
        if runtime_loop is None:
            runtime_loop = asyncio.get_event_loop()
        runtime_loop.run_until_complete(run_clients())
        storage.sync_now("client_stopped")

    except Exception as exc:
        try:
            storage.sync_now("before_safe_mode_restart")
        except Exception as sync_error:
            logger.warning("[MongoDB] Sync before restart failed: %s", sync_error)
        if not safe_mode:
            logger.exception("[Zelretch] Error detected; restarting in safe mode")
            logger.warning("[Zelretch] Restarting in safe mode (only core modules)...")
            os.execv(sys.executable, [sys.executable] + sys.argv + ["--safe"])
        else:
            logger.critical("[Zelretch] Critical error in safe mode: %s", exc, exc_info=True)


if __name__ == "__main__":
    check_structure()
    setup_logging()
    logger.info("Starting Zelretch...")
    autoupdater()

    # Install the Telegram log-channel handler after dependency installation,
    # because autoupdater rebuilds the root logger.
    from operational_logger import (
        configure_operational_logging,
        report_event,
        report_exception,
    )

    configure_operational_logging()
    startup_kind = "restart" if len(sys.argv) >= 4 else "normal"
    report_event(
        "INFO",
        "ZELRETCH_RESTART" if startup_kind == "restart" else "ZELRETCH_STARTUP",
        "Zelretch process startup has begun.",
        metadata={
            "startup_kind": startup_kind,
            "safe_mode": "--safe" in sys.argv,
            "pid": os.getpid(),
        },
    )

    try:
        # Import after dependency installation so first-time non-Docker installs work.
        from mongodb_storage import get_storage

        storage = get_storage(required=True)
        storage.restore_runtime_state()
        convert_modules()

        # Addons are enabled by default. Refresh the managed repository
        # before Kurigram validates and loads addons. MongoDB retains the last synchronized addon set when GitHub is temporarily unavailable.
        from addons_manager import synchronize_addons

        synchronize_addons()
        storage.start_background_sync()
        storage.sync_now("startup")
        run_zelretch(storage)
    except Exception as exc:
        report_exception(
            "CRITICAL",
            "CRITICAL_SYSTEM_EVENT",
            "Zelretch terminated during startup or top-level execution.",
            exc,
        )
        logger.critical("Zelretch terminated: %s", exc, exc_info=True)
        raise
