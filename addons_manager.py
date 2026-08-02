# -*- coding: utf-8 -*-
"""Automatic Addons synchronization for Zelretch.

The configured GitHub repository is the managed source for external modules.
Modules are copied into ``modules/loaded`` where the existing validator and
loader activate them. A manifest tracks only repository-managed files so that
manually uploaded modules are never removed by synchronization.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

LOGGER = logging.getLogger(__name__)

DEFAULT_REPOSITORY = "https://github.com/SiamTestingProject/Addons"
DEFAULT_BRANCH = "main"
LOADED_DIRECTORY = Path("modules/loaded")
BROKEN_DIRECTORY = Path("broken_modules")
MANIFEST_PATH = Path("userdata/addons_manifest.json")
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


@dataclass(frozen=True)
class AddonsSyncResult:
    enabled: bool
    repository: str
    branch: str
    downloaded: bool
    installed: int
    updated: int
    unchanged: int
    removed: int
    rejected: int
    retained_cached_modules: bool = False
    error: str = ""


def automatic_addons_enabled() -> bool:
    """Return True unless automatic Addons support is explicitly disabled."""
    value = os.environ.get("AUTO_ADDONS", os.environ.get("AUTO_" + "CUSTOM_MODULES", "true")).strip().lower()
    return value not in FALSE_VALUES


def configured_repository() -> str:
    return (os.environ.get("ADDONS_REPO") or os.environ.get("CUSTOM_" + "MODULES_REPO") or DEFAULT_REPOSITORY).strip().rstrip("/")


def configured_branch() -> str:
    return (os.environ.get("ADDONS_BRANCH") or os.environ.get("CUSTOM_" + "MODULES_BRANCH") or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH


def _safe_filename(source_name: str) -> str:
    path = PurePosixPath(source_name)
    stem = re.sub(r"[^\w]+", "_", path.stem, flags=re.UNICODE).strip("_") or "module"
    if stem[0].isdigit():
        stem = f"module_{stem}"
    return f"{stem}.py"


def _archive_url(repository: str, branch: str) -> str:
    parsed = urllib.parse.urlparse(repository)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() in {
        "github.com",
        "www.github.com",
    }:
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2:
            owner = urllib.parse.quote(parts[0], safe="")
            repo = urllib.parse.quote(parts[1].removesuffix(".git"), safe="")
            encoded_branch = urllib.parse.quote(branch, safe="")
            return f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{encoded_branch}"
    if repository.lower().endswith(".zip"):
        return repository
    raise ValueError(
        "ADDONS_REPO must be a GitHub repository URL or a direct ZIP archive URL"
    )


def _read_manifest() -> Dict[str, object]:
    try:
        value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _managed_filenames(manifest: Dict[str, object]) -> set[str]:
    entries = manifest.get("managed_modules")
    if not isinstance(entries, list):
        return set()
    names: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict):
            value = entry.get("filename")
            if isinstance(value, str) and value.endswith(".py"):
                names.add(value)
    return names


def _download_archive(url: str) -> bytes:
    try:
        timeout = max(5, min(120, int(os.environ.get("ADDONS_TIMEOUT", "25"))))
    except ValueError:
        timeout = 25
    try:
        attempts = max(1, min(5, int(os.environ.get("ADDONS_DOWNLOAD_ATTEMPTS", "2"))))
    except ValueError:
        attempts = 2

    last_error: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Zelretch-Addons/1.0",
                    "Accept": "application/zip, application/octet-stream;q=0.9, */*;q=0.1",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                declared_length = response.headers.get("Content-Length")
                if declared_length and int(declared_length) > MAX_ARCHIVE_BYTES:
                    raise ValueError("Addons archive exceeds the 25 MiB safety limit")
                payload = response.read(MAX_ARCHIVE_BYTES + 1)
            if len(payload) > MAX_ARCHIVE_BYTES:
                raise ValueError("Addons archive exceeds the 25 MiB safety limit")
            if not payload:
                raise ValueError("Addons repository returned an empty archive")
            return payload
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(5, attempt * 2))
    raise RuntimeError(f"Cannot download Addons archive: {last_error}") from last_error


def _select_modules(payload: bytes) -> Tuple[List[Tuple[str, str, bytes]], int]:
    selected: List[Tuple[str, str, bytes]] = []
    rejected = 0
    used_names: set[str] = set()

    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        for member in sorted(archive.infolist(), key=lambda item: item.filename.casefold()):
            if member.is_dir():
                continue
            pure = PurePosixPath(member.filename)
            if pure.is_absolute() or ".." in pure.parts or not pure.parts:
                rejected += 1
                continue
            if any(part.startswith(".") or part == "__pycache__" for part in pure.parts):
                continue
            if pure.suffix.lower() != ".py" or pure.name == "__init__.py":
                continue

            data = archive.read(member)
            try:
                text = data.decode("utf-8-sig")
                compile(text, pure.as_posix(), "exec")
            except (UnicodeDecodeError, SyntaxError):
                rejected += 1
                BROKEN_DIRECTORY.mkdir(parents=True, exist_ok=True)
                broken_name = _safe_filename(pure.name)
                (BROKEN_DIRECTORY / broken_name).write_bytes(data)
                continue

            target_name = _safe_filename(pure.name)
            if target_name in used_names:
                parent_bits = [_safe_filename(f"{part}.py")[:-3] for part in pure.parts[1:-1]]
                prefix = "_".join(bit for bit in parent_bits if bit)
                target_name = f"{prefix}_{target_name}" if prefix else target_name
                suffix = 2
                base = target_name[:-3]
                while target_name in used_names:
                    target_name = f"{base}_{suffix}.py"
                    suffix += 1
            used_names.add(target_name)
            selected.append((pure.as_posix(), target_name, data))

    if not selected:
        raise ValueError("The Addons archive contains no valid Python modules")
    return selected, rejected


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _report(level: str, event_type: str, description: str, **metadata: object) -> None:
    try:
        from operational_logger import report_event

        report_event(level, event_type, description, metadata=metadata)
    except Exception:
        LOGGER.debug("Operational logger is not ready for %s", event_type, exc_info=True)


def synchronize_addons() -> AddonsSyncResult:
    """Synchronize and enable modules from the configured repository.

    Download failures are nonfatal. MongoDB persists ``modules/loaded``, so previously synchronized addons remain active
    until the remote repository is reachable again.
    """

    repository = configured_repository()
    branch = configured_branch()
    if not automatic_addons_enabled():
        LOGGER.info("[Addons] Automatic addon synchronization is explicitly disabled")
        return AddonsSyncResult(False, repository, branch, False, 0, 0, 0, 0, 0)

    LOADED_DIRECTORY.mkdir(parents=True, exist_ok=True)
    BROKEN_DIRECTORY.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    previous_manifest = _read_manifest()
    previous_managed = _managed_filenames(previous_manifest)

    try:
        payload = _download_archive(_archive_url(repository, branch))
        modules, rejected = _select_modules(payload)
    except Exception as exc:
        cached = any((LOADED_DIRECTORY / name).exists() for name in previous_managed)
        LOGGER.warning(
            "[Addons] Remote synchronization failed; retaining cached modules: %s",
            exc,
            exc_info=True,
        )
        _report(
            "WARNING",
            "ADDONS_SYNC_FAILURE",
            "Addons could not be refreshed; the existing MongoDB-cached addons remain enabled.",
            repository=repository,
            branch=branch,
            cached_modules_retained=cached,
            error=str(exc),
        )
        return AddonsSyncResult(
            True, repository, branch, False, 0, 0, 0, 0, 0, cached, str(exc)
        )

    installed = updated = unchanged = 0
    manifest_entries: List[Dict[str, str]] = []
    current_managed: set[str] = set()

    for source_path, filename, data in modules:
        destination = LOADED_DIRECTORY / filename
        digest = hashlib.sha256(data).hexdigest()
        current_managed.add(filename)
        if not destination.exists():
            _atomic_write(destination, data)
            installed += 1
        elif hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            _atomic_write(destination, data)
            updated += 1
        else:
            unchanged += 1
        manifest_entries.append({"source_path": source_path, "filename": filename, "sha256": digest})

    removed = 0
    for stale_name in sorted(previous_managed - current_managed):
        stale_path = LOADED_DIRECTORY / stale_name
        try:
            if stale_path.is_file():
                stale_path.unlink()
                removed += 1
        except OSError as exc:
            LOGGER.warning("[Addons] Could not remove stale managed module %s: %s", stale_name, exc)

    manifest = {
        "schema_version": 1,
        "repository": repository,
        "branch": branch,
        "archive_sha256": hashlib.sha256(payload).hexdigest(),
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "managed_modules": manifest_entries,
    }
    _atomic_write(MANIFEST_PATH, (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))

    LOGGER.info(
        "[Addons] Enabled %d module(s) from %s (%d new, %d updated, %d unchanged, %d removed, %d rejected)",
        len(manifest_entries), repository, installed, updated, unchanged, removed, rejected,
    )
    _report(
        "INFO" if rejected == 0 else "WARNING",
        "ADDONS_SYNC_COMPLETE",
        "Addons were synchronized and enabled automatically.",
        repository=repository,
        branch=branch,
        total_modules=len(manifest_entries),
        installed=installed,
        updated=updated,
        unchanged=unchanged,
        removed=removed,
        rejected=rejected,
    )
    return AddonsSyncResult(
        True, repository, branch, True, installed, updated, unchanged, removed, rejected
    )


if __name__ == "__main__":
    result = synchronize_addons()
    print(json.dumps(result.__dict__, indent=2, ensure_ascii=False))
