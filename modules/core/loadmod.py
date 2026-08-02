import importlib
import os
import logging
import sys
from importlib.machinery import SourceFileLoader

import wget
from pyrogram import Client

from operational_logger import wrap_message_handler

from command import zel_command, zel_sudo, who_message, get_text
from modules.core.plugin_validator import PluginValidator

filename = os.path.basename(__file__)
Module_Name = 'Loadmod'

LANGUAGES = {
    "en": {
        "checking": "<emoji id='5190903199137013741'>🔍</emoji> <b>Checking and loading module</b>",
        "validation_failed": "<emoji id='5210952531676504517'>❌</emoji> <b>Plugin validation failed</b>\n<code>{error}</code>",
        "no_module": "<emoji id='5210952531676504517'>❌</emoji> <b>Specify a link, reply with a .py file, or module name</b>",
        "success": "<emoji id='5237699328843200968'>✅</emoji> <b>Module {module_name} loaded successfully!</b>",
        "error": "<emoji id='5210952531676504517'>❌</emoji> <b>Error while loading</b>\n<code>{error}</code>"
    },
    "ru": {
        "checking": "<emoji id='5190903199137013741'>🔍</emoji> <b>Проверка и загрузка модуля</b>",
        "validation_failed": "<emoji id='5210952531676504517'>❌</emoji> <b>Ошибка валидации плагина</b>\n<code>{error}</code>",
        "no_module": "<emoji id='5210952531676504517'>❌</emoji> <b>Укажите ссылку, ответьте файлом .py или названием модуля</b>",
        "success": "<emoji id='5237699328843200968'>✅</emoji> <b>Модуль {module_name} успешно загружен!</b>",
        "error": "<emoji id='5210952531676504517'>❌</emoji> <b>Ошибка при загрузке</b>\n<code>{error}</code>"
    },
    "ua": {
        "checking": "<emoji id='5190903199137013741'>🔍</emoji> <b>Перевірка та завантаження модуля</b>",
        "validation_failed": "<emoji id='5210952531676504517'>❌</emoji> <b>Помилка валідації плагіна</b>\n<code>{error}</code>",
        "no_module": "<emoji id='5210952531676504517'>❌</emoji> <b>Вкажіть посилання, відповісте на .py або назвіть модуль</b>",
        "success": "<emoji id='5237699328843200968'>✅</emoji> <b>Модуль {module_name} успішно завантажено!</b>",
        "error": "<emoji id='5210952531676504517'>❌</emoji> <b>Помилка завантаження</b>\n<code>{error}</code>"
    }
}


def _iter_plugin_handlers(module):
    for obj in module.__dict__.values():
        if callable(obj) and hasattr(obj, "handlers"):
            for h in getattr(obj, "handlers", []):
                yield h


def _remove_module_handlers(client: Client, module_qualname: str):
    try:
        mod = importlib.import_module(module_qualname)
    except Exception:
        module_stem = module_qualname.rsplit('.', 1)[-1]
        module_path = os.path.join('modules', 'loaded', f'{module_stem}.py')
        if os.path.exists(module_path):
            mod = SourceFileLoader(module_qualname, module_path).load_module()
        else:
            return
    for h in list(_iter_plugin_handlers(mod)):
        try:
            handler, group = h
            if hasattr(client.dispatcher, 'groups') and group in client.dispatcher.groups:
                if handler in client.dispatcher.groups[group]:
                    client.remove_handler(handler, group)
        except Exception:
            pass
    sys.modules.pop(module_qualname, None)


def _load_module_handlers(client: Client, module_qualname: str):
    importlib.invalidate_caches()
    if module_qualname in sys.modules:
        mod = importlib.reload(sys.modules[module_qualname])
    else:
        try:
            mod = importlib.import_module(module_qualname)
        except Exception:
            module_stem = module_qualname.rsplit('.', 1)[-1]
            module_path = os.path.join('modules', 'loaded', f'{module_stem}.py')
            mod = SourceFileLoader(module_qualname, module_path).load_module()
    for h in _iter_plugin_handlers(mod):
        handler, group = h
        wrap_message_handler(handler, group)
        client.add_handler(handler, group)


@Client.on_message(zel_command("loadmod", Module_Name, filename, "[link to the module/reply]") & zel_sudo())
async def loadmod(client, message):
    message = await who_message(client, message)
    checking_text = get_text("loadmod", "checking", LANGUAGES=LANGUAGES)
    await message.edit(checking_text)
    
    validator = PluginValidator()
    
    try:
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else None

        filename_var = None

        if arg and (arg.startswith("http://") or arg.startswith("https://")):
            temp_file = wget.download(arg, out="temp/")
            
            original_filename = os.path.basename(arg)
            if not original_filename.endswith('.py'):
                original_filename += '.py'
                
            success, final_path, error_message = validator.validate_and_convert_plugin(temp_file, original_filename)
            
            if not success:
                error_text = get_text("loadmod", "validation_failed", LANGUAGES=LANGUAGES, error=error_message)
                await message.edit(error_text)
                return
                
            filename_var = final_path
            if os.path.exists(temp_file):
                os.remove(temp_file)
                
        elif getattr(message, "reply_to_message", None) and getattr(message.reply_to_message, "document", None):
            original_filename = message.reply_to_message.document.file_name
            temp_file = await client.download_media(message.reply_to_message.document, file_name='temp/')
            
            success, final_path, error_message = validator.validate_and_convert_plugin(temp_file, original_filename)
            
            if not success:
                error_text = get_text("loadmod", "validation_failed", LANGUAGES=LANGUAGES, error=error_message)
                await message.edit(error_text)
                return
                
            filename_var = final_path
            if os.path.exists(temp_file):
                os.remove(temp_file)
                
        elif arg:
            filename_var = arg if arg.endswith('.py') else f"{arg}.py"
            
        if not filename_var:
            no_module_text = get_text("loadmod", "no_module", LANGUAGES=LANGUAGES)
            await message.edit(no_module_text)
            return
            
        module_stem = os.path.splitext(os.path.basename(str(filename_var)))[0]
        module_qualname = f"modules.loaded.{module_stem}"
        _remove_module_handlers(client, module_qualname)
        _load_module_handlers(client, module_qualname)

        success_text = get_text("loadmod", "success", LANGUAGES=LANGUAGES, module_name=module_stem)
        await message.edit(success_text)
        
    except Exception as error:
        logging.exception("[Command: loadmod] Module loading failed: %s", error)
        error_text = get_text("loadmod", "error", LANGUAGES=LANGUAGES, error=str(error))
        await message.edit(error_text)
