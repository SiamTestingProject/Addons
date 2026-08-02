# -*- coding: utf-8 -*-
"""MongoDB-backed persistence for Zelretch.

MongoDB is the only durable data store. Kurigram runs with an in-memory
Telegram session loaded from MongoDB, while legacy INI/JSON/plugin files are
kept as a runtime compatibility cache and synchronized to MongoDB GridFS.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import io
import logging
import os
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Optional

from gridfs import GridFSBucket
from pymongo import MongoClient
from pymongo.errors import PyMongoError

LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 3
STATE_COLLECTION = "zelretch_state"
GRIDFS_BUCKET = "zelretch_runtime"
LEGACY_PROJECT_KEY = "fox" + "userbot"
LEGACY_STATE_COLLECTION = LEGACY_PROJECT_KEY + "_state"
LEGACY_GRIDFS_BUCKET = LEGACY_PROJECT_KEY + "_runtime"
PERSISTED_DIRECTORIES = (
    Path("userdata"),
    Path("triggers"),
    Path("modules/loaded"),
    Path("broken_modules"),
)
IGNORED_PARTS = {"__pycache__", ".git"}
IGNORED_SUFFIXES = {".pyc", ".pyo", ".log"}


class MongoStorageError(RuntimeError):
    """Raised when required MongoDB persistence is unavailable."""


class MongoStorage:
    def __init__(self, required: bool = True) -> None:
        self.uri = (os.environ.get("MONGODB_URI") or "").strip()
        self.instance_id = (os.environ.get("ZELRETCH_INSTANCE_ID") or os.environ.get("FOX_INSTANCE_ID") or "default").strip() or "default"
        self.required = required
        self._sync_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._sync_thread: Optional[threading.Thread] = None
        self._client: Optional[MongoClient] = None
        self._database = None
        self._state = None
        self._bucket: Optional[GridFSBucket] = None

        if not self.uri:
            if required:
                raise MongoStorageError(
                    "MONGODB_URI is required. Add it as a Hugging Face Space secret."
                )
            return

        try:
            self._client = MongoClient(
                self.uri,
                serverSelectionTimeoutMS=15_000,
                connectTimeoutMS=15_000,
                socketTimeoutMS=30_000,
                appname="Zelretch",
            )
            self._client.admin.command("ping")

            configured_name = (os.environ.get("MONGODB_DATABASE") or "").strip()
            if configured_name:
                database_name = configured_name
            else:
                try:
                    default_database = self._client.get_default_database()
                    database_name = default_database.name
                except Exception:
                    database_names = set(self._client.list_database_names())
                    database_name = LEGACY_PROJECT_KEY if LEGACY_PROJECT_KEY in database_names else "zelretch"

            self._database = self._client[database_name]
            self._state = self._database[STATE_COLLECTION]
            self._bucket = GridFSBucket(self._database, bucket_name=GRIDFS_BUCKET)
            self._migrate_legacy_state()
            self._state.update_one(
                {"_id": self.instance_id},
                {
                    "$setOnInsert": {
                        "schema_version": SCHEMA_VERSION,
                        "created_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
        except Exception as exc:
            self.close()
            raise MongoStorageError(f"Cannot connect to MongoDB: {exc}") from exc

    def _migrate_legacy_state(self) -> None:
        """Copy a compatible pre-rebrand record into the Zelretch collections once."""
        try:
            existing = self._state.find_one({"_id": self.instance_id})
            if existing and (
                existing.get("telegram_session")
                or existing.get("snapshot_id")
                or existing.get("telegram_services")
            ):
                return

            legacy_state = self._database[LEGACY_STATE_COLLECTION]
            legacy = legacy_state.find_one({"_id": self.instance_id})
            if not legacy:
                return

            migrated = dict(legacy)
            migrated.pop("_id", None)
            old_snapshot_id = migrated.get("snapshot_id")
            if old_snapshot_id is not None:
                legacy_bucket = GridFSBucket(self._database, bucket_name=LEGACY_GRIDFS_BUCKET)
                with legacy_bucket.open_download_stream(old_snapshot_id) as stream:
                    payload = stream.read()
                new_snapshot_id = self._bucket.upload_from_stream(
                    f"{self.instance_id}-legacy-migration.zip",
                    io.BytesIO(payload),
                    metadata={
                        "instance_id": self.instance_id,
                        "schema_version": SCHEMA_VERSION,
                        "reason": "zelretch_rebrand_migration",
                    },
                )
                migrated["snapshot_id"] = new_snapshot_id

            migrated["schema_version"] = SCHEMA_VERSION
            migrated["migrated_from_legacy_at"] = datetime.now(timezone.utc)
            self._state.update_one(
                {"_id": self.instance_id},
                {"$set": migrated},
                upsert=True,
            )
            LOGGER.info("[MongoDB] Migrated the existing runtime state to Zelretch collections")
        except Exception as exc:
            LOGGER.warning("[MongoDB] Legacy-state migration was skipped: %s", exc, exc_info=True)

    @property
    def enabled(self) -> bool:
        return self._client is not None and self._state is not None and self._bucket is not None

    def ping(self) -> None:
        self._require_enabled()
        self._client.admin.command("ping")

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise MongoStorageError("MongoDB storage is not configured")

    def has_session(self) -> bool:
        self._require_enabled()
        doc = self._state.find_one(
            {"_id": self.instance_id, "telegram_session": {"$type": "string"}},
            {"telegram_session": 1},
        )
        return bool(doc and doc.get("telegram_session"))

    def get_session_string(self) -> Optional[str]:
        self._require_enabled()
        doc = self._state.find_one({"_id": self.instance_id}, {"telegram_session": 1})
        if not doc:
            return None
        value = doc.get("telegram_session")
        return value if isinstance(value, str) and value.strip() else None

    def save_session_string(self, session_string: str) -> None:
        self._require_enabled()
        if not isinstance(session_string, str) or not session_string.strip():
            raise MongoStorageError("Refusing to save an empty Telegram session")
        self._state.update_one(
            {"_id": self.instance_id},
            {
                "$set": {
                    "telegram_session": session_string.strip(),
                    "session_updated_at": datetime.now(timezone.utc),
                    "schema_version": SCHEMA_VERSION,
                }
            },
            upsert=True,
        )
        LOGGER.info("[MongoDB] Telegram session saved")

    def clear_session(self) -> None:
        self._require_enabled()
        self._state.update_one(
            {"_id": self.instance_id},
            {
                "$unset": {"telegram_session": "", "session_updated_at": ""},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )

    def get_telegram_service_config(self) -> dict:
        """Return persisted companion-bot and log-channel settings.

        BOT_TOKEN and LOG_CHANNEL_ID environment variables remain authoritative;
        this MongoDB record is the durable fallback used when those variables are
        absent on a later deployment.
        """
        self._require_enabled()
        doc = self._state.find_one(
            {"_id": self.instance_id},
            {"telegram_services": 1},
        ) or {}
        value = doc.get("telegram_services")
        return dict(value) if isinstance(value, dict) else {}

    def save_telegram_service_bot(
        self,
        *,
        bot_token: str,
        bot_username: str,
        bot_id: str = "",
        source: str = "runtime",
    ) -> None:
        self._require_enabled()
        if not str(bot_token or "").strip():
            raise MongoStorageError("Refusing to save an empty BOT_TOKEN")
        if not str(bot_username or "").strip():
            raise MongoStorageError("Refusing to save a service bot without a username")
        now = datetime.now(timezone.utc)
        self._state.update_one(
            {"_id": self.instance_id},
            {
                "$set": {
                    "telegram_services.bot_token": str(bot_token).strip(),
                    "telegram_services.bot_username": str(bot_username).strip().lstrip("@"),
                    "telegram_services.bot_id": str(bot_id or "").strip(),
                    "telegram_services.bot_source": str(source or "runtime"),
                    "telegram_services.bot_updated_at": now,
                    "telegram_services.updated_at": now,
                    "schema_version": SCHEMA_VERSION,
                }
            },
            upsert=True,
        )
        LOGGER.info("[MongoDB] Telegram service bot configuration saved")

    def save_telegram_log_channel(
        self,
        *,
        channel_id: str,
        title: str = "",
        source: str = "runtime",
    ) -> None:
        self._require_enabled()
        if not str(channel_id or "").strip():
            raise MongoStorageError("Refusing to save an empty LOG_CHANNEL_ID")
        now = datetime.now(timezone.utc)
        self._state.update_one(
            {"_id": self.instance_id},
            {
                "$set": {
                    "telegram_services.log_channel_id": str(channel_id).strip(),
                    "telegram_services.log_channel_title": str(title or "").strip(),
                    "telegram_services.channel_source": str(source or "runtime"),
                    "telegram_services.channel_updated_at": now,
                    "telegram_services.updated_at": now,
                    "schema_version": SCHEMA_VERSION,
                }
            },
            upsert=True,
        )
        LOGGER.info("[MongoDB] Telegram logging channel configuration saved")

    @staticmethod
    def _iter_persisted_files():
        for root in PERSISTED_DIRECTORIES:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.as_posix()
                parts = set(path.parts)
                if parts & IGNORED_PARTS or path.suffix.lower() in IGNORED_SUFFIXES:
                    continue
                yield path, relative

    @staticmethod
    def _build_snapshot() -> tuple[bytes, str, int]:
        output = io.BytesIO()
        file_count = 0
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path, relative in MongoStorage._iter_persisted_files():
                data = path.read_bytes()
                info = zipfile.ZipInfo(relative)
                # Deterministic metadata prevents unchanged files from producing a new hash.
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, data)
                file_count += 1
        payload = output.getvalue()
        return payload, hashlib.sha256(payload).hexdigest(), file_count

    @staticmethod
    def _safe_extract(payload: bytes) -> int:
        restored = 0
        allowed_roots = {directory.as_posix().split("/")[0] for directory in PERSISTED_DIRECTORIES}
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                pure_path = PurePosixPath(member.filename)
                if pure_path.is_absolute() or ".." in pure_path.parts or not pure_path.parts:
                    raise MongoStorageError(f"Unsafe path in MongoDB snapshot: {member.filename}")
                if pure_path.parts[0] not in allowed_roots:
                    raise MongoStorageError(f"Unexpected path in MongoDB snapshot: {member.filename}")
                destination = Path(*pure_path.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(member))
                restored += 1
        return restored

    def restore_runtime_state(self) -> bool:
        self._require_enabled()
        with self._sync_lock:
            doc = self._state.find_one({"_id": self.instance_id}, {"snapshot_id": 1, "snapshot_sha256": 1})
            snapshot_id = doc.get("snapshot_id") if doc else None
            if snapshot_id is None:
                LOGGER.info("[MongoDB] No runtime snapshot found; starting with repository defaults")
                return False
            try:
                with self._bucket.open_download_stream(snapshot_id) as stream:
                    payload = stream.read()
                expected_hash = doc.get("snapshot_sha256")
                actual_hash = hashlib.sha256(payload).hexdigest()
                if expected_hash and expected_hash != actual_hash:
                    raise MongoStorageError("MongoDB runtime snapshot checksum mismatch")
                restored = self._safe_extract(payload)
                LOGGER.info("[MongoDB] Restored %d runtime file(s)", restored)
                return True
            except Exception as exc:
                raise MongoStorageError(f"Cannot restore MongoDB runtime state: {exc}") from exc

    def sync_now(self, reason: str = "manual", force: bool = False) -> bool:
        self._require_enabled()
        with self._sync_lock:
            payload, digest, file_count = self._build_snapshot()
            current = self._state.find_one(
                {"_id": self.instance_id}, {"snapshot_id": 1, "snapshot_sha256": 1}
            ) or {}
            if not force and current.get("snapshot_sha256") == digest:
                return False

            filename = f"{self.instance_id}-{int(time.time())}.zip"
            old_snapshot_id = current.get("snapshot_id")
            try:
                new_snapshot_id = self._bucket.upload_from_stream(
                    filename,
                    io.BytesIO(payload),
                    metadata={
                        "instance_id": self.instance_id,
                        "schema_version": SCHEMA_VERSION,
                        "sha256": digest,
                        "file_count": file_count,
                        "reason": reason,
                    },
                )
                self._state.update_one(
                    {"_id": self.instance_id},
                    {
                        "$set": {
                            "snapshot_id": new_snapshot_id,
                            "snapshot_sha256": digest,
                            "snapshot_file_count": file_count,
                            "snapshot_updated_at": datetime.now(timezone.utc),
                            "updated_at": datetime.now(timezone.utc),
                            "schema_version": SCHEMA_VERSION,
                        }
                    },
                    upsert=True,
                )
                if old_snapshot_id and old_snapshot_id != new_snapshot_id:
                    try:
                        self._bucket.delete(old_snapshot_id)
                    except Exception as cleanup_error:
                        LOGGER.warning("[MongoDB] Could not remove old snapshot: %s", cleanup_error, exc_info=True)
                LOGGER.info("[MongoDB] Synced %d runtime file(s) (%s)", file_count, reason)
                return True
            except Exception as exc:
                raise MongoStorageError(f"Cannot synchronize runtime state to MongoDB: {exc}") from exc

    def start_background_sync(self) -> None:
        self._require_enabled()
        if self._sync_thread and self._sync_thread.is_alive():
            return
        try:
            interval = max(5, int(os.environ.get("MONGODB_SYNC_INTERVAL", "15")))
        except ValueError:
            interval = 15

        self._stop_event.clear()

        def worker() -> None:
            while not self._stop_event.wait(interval):
                try:
                    self.sync_now("periodic")
                except Exception as exc:
                    LOGGER.exception("[MongoDB] Periodic sync failed: %s", exc)

        self._sync_thread = threading.Thread(
            target=worker,
            name="zelretch-mongodb-sync",
            daemon=True,
        )
        self._sync_thread.start()
        atexit.register(self._atexit_sync)
        LOGGER.info("[MongoDB] Background synchronization enabled (%ss)", interval)

    def _atexit_sync(self) -> None:
        try:
            self.sync_now("shutdown")
        except Exception as exc:
            LOGGER.warning("[MongoDB] Final sync failed: %s", exc, exc_info=True)
        self.close()

    def close(self) -> None:
        self._stop_event.set()
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self._database = None
        self._state = None
        self._bucket = None


_STORAGE: Optional[MongoStorage] = None
_STORAGE_LOCK = threading.Lock()


def get_storage(required: bool = True) -> MongoStorage:
    global _STORAGE
    with _STORAGE_LOCK:
        if _STORAGE is None:
            _STORAGE = MongoStorage(required=required)
        elif required and not _STORAGE.enabled:
            raise MongoStorageError("MongoDB storage is required but is not configured")
        return _STORAGE


def sync_runtime_state(reason: str = "command") -> None:
    """Synchronize immediately before commands that restart the process."""
    get_storage(required=True).sync_now(reason)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Zelretch MongoDB storage helper")
    parser.add_argument("command", choices=("restore", "sync", "has-session", "status"))
    args = parser.parse_args()

    try:
        storage = get_storage(required=True)
        if args.command == "restore":
            storage.restore_runtime_state()
            return 0
        if args.command == "sync":
            storage.sync_now("cli", force=True)
            return 0
        if args.command == "has-session":
            return 0 if storage.has_session() else 1
        if args.command == "status":
            storage.ping()
            print(
                f"MongoDB connected; instance={storage.instance_id}; "
                f"session={'present' if storage.has_session() else 'missing'}"
            )
            return 0
    except (MongoStorageError, PyMongoError) as exc:
        print(f"MongoDB storage error: {exc}", file=os.sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
