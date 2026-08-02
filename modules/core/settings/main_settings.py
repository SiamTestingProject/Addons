"""Shared Zelretch runtime registries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

version = "3.0.0"
module_list: Dict[str, list[str]] = {}
file_list: Dict[str, str] = {}
module_metadata: Dict[str, Dict[str, str]] = {}

CORE_MODULE_METADATA = {'1banner.py': ('System Loader', '⚡', 'Core', 'Initializes the Zelretch module loader and startup banner.'), '1merge_from_old_version.py': ('Migration', '🧭', 'Core', 'Migrates compatible settings from older local installations.'), 'alias.py': ('Alias Manager', '🏷️', 'Core', 'Creates and manages custom aliases for Zelretch commands.'), 'backup.py': ('Backup & Restore', '💾', 'Core', 'Exports, restores, and backs up runtime data and installed modules.'), 'eval.py': ('Python Executor', '🧪', 'Developer Tools', 'Executes owner-authorized Python snippets for diagnostics and administration.'), 'find_id.py': ('ID Finder', '🆔', 'Core', 'Shows Telegram IDs for users, chats, messages, and replied entities.'), 'help.py': ('Command Center', '✨', 'Core', 'Opens the interactive inline command catalog and module descriptions.'), 'info.py': ('System Overview', 'ℹ️', 'Core', 'Displays Zelretch version, runtime, platform, uptime, and developer information.'), 'lang.py': ('Language', '🌐', 'Core', 'Changes the interface language used by supported core modules.'), 'loadmod.py': ('Module Installer', '📦', 'Developer Tools', 'Downloads, validates, and loads a compatible addon module.'), 'ping.py': ('Connection Test', '🏓', 'Core', 'Measures Telegram response latency and confirms that Zelretch is online.'), 'restarter.py': ('Restart & Update', '🔄', 'Core', 'Restarts Zelretch and applies supported source updates safely.'), 'sh.py': ('Shell', '🖥️', 'Developer Tools', 'Runs owner-authorized shell commands on the host system.'), 'sprefix.py': ('Prefix', '⌨️', 'Core', 'Changes the command prefix used by Zelretch.'), 'sudousers.py': ('Sudo Access', '🔐', 'Administration', 'Manages trusted users who may execute permitted Zelretch commands.'), 'theme.py': ('Appearance', '🎨', 'Core', 'Customizes help and information card text and media.'), 'unloadmod.py': ('Module Unloader', '📤', 'Developer Tools', 'Disables and removes a loaded addon module.'), 'uploadmod.py': ('Module Exporter', '📁', 'Developer Tools', 'Uploads or exports installed addon module files.'), 'uptime.py': ('Uptime', '⏱️', 'Core', 'Tracks process start time for status and information views.'), 'plugin_loader.py': ('Addon Loader', '🧩', 'Core', 'Loads validated addons from the managed Addons repository.'), 'plugin_validator.py': ('Addon Validator', '✅', 'Core', 'Validates addon syntax and converts supported legacy formats.')}


def add_command_help(module_name: str, text: str) -> None:
    if module_name not in module_list:
        module_list[module_name] = []
    if text not in module_list[module_name]:
        module_list[module_name].append(text)


def register_module_metadata(filename: str, metadata: Dict[str, Any] | None) -> None:
    if not metadata:
        return
    clean = Path(str(filename)).name
    module_metadata[clean] = {
        "title": str(metadata.get("title") or Path(clean).stem.replace("_", " ").title()),
        "icon": str(metadata.get("icon") or "🧩"),
        "category": str(metadata.get("category") or "Other"),
        "description": str(metadata.get("description") or "Zelretch module."),
        "developer": str(metadata.get("developer") or "Siam Chowdhury"),
        "github": str(metadata.get("github") or "https://github.com/ChowdhurySiam"),
        "telegram": str(metadata.get("telegram") or "https://t.me/Ch0wdhury_Siam"),
    }


def get_module_metadata(module_name: str, filename: str = "") -> Dict[str, str]:
    clean = Path(str(filename or file_list.get(module_name, ""))).name
    if clean in module_metadata:
        return dict(module_metadata[clean])
    if clean in CORE_MODULE_METADATA:
        title, icon, category, description = CORE_MODULE_METADATA[clean]
        return {
            "title": title,
            "icon": icon,
            "category": category,
            "description": description,
            "developer": "Siam Chowdhury",
            "github": "https://github.com/ChowdhurySiam",
            "telegram": "https://t.me/Ch0wdhury_Siam",
        }
    return {
        "title": str(module_name).replace("_", " ").strip().title(),
        "icon": "🧩",
        "category": "Other",
        "description": "A Zelretch command module.",
        "developer": "Siam Chowdhury",
        "github": "https://github.com/ChowdhurySiam",
        "telegram": "https://t.me/Ch0wdhury_Siam",
    }
