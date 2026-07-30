# Moved from main Ultroid package

This expanded Addons package contains the original addon plugins plus the official command plugins moved out of the main deployment package.

## Official plugins added to this addon package

- `_chatactions.py`
- `_help.py`
- `_inline.py`
- `_ultroid.py`
- `_userlogs.py`
- `_wspr.py`
- `admintools.py`
- `afk.py`
- `aiwrapper.py`
- `antiflood.py`
- `asstcmd.py`
- `audiotools.py`
- `autoban.py`
- `autopic.py`
- `beautify.py`
- `blacklist.py`
- `bot.py`
- `broadcast.py`
- `button.py`
- `calculator.py`
- `channelhacks.py`
- `chatbot.py`
- `chats.py`
- `cleanaction.py`
- `compressor.py`
- `converter.py`
- `core.py`
- `database.py`
- `delayspam.py`
- `devtools.py`
- `downloadupload.py`
- `echo.py`
- `extra.py`
- `fakeaction.py`
- `fileshare.py`
- `filter.py`
- `fontgen.py`
- `forcesubscribe.py`
- `gdrive.py`
- `giftools.py`
- `glitch.py`
- `globaltools.py`
- `greetings.py`
- `imagetools.py`
- `locks.py`
- `logo.py`
- `mediatools.py`
- `misc.py`
- `mute.py`
- `nightmode.py`
- `notes.py`
- `nsfwfilter.py`
- `other.py`
- `pdftools.py`
- `pmpermit.py`
- `polls.py`
- `profanityfilter.py`
- `profile.py`
- `qrcode.py`
- `resize.py`
- `schedulemsg.py`
- `search.py`
- `snips.py`
- `specialtools.py`
- `stickertools.py`
- `stories.py`
- `sudo.py`
- `tag.py`
- `tools.py`
- `twitter.py`
- `unsplash.py`
- `usage.py`
- `utilities.py`
- `variables.py`
- `vctools.py`
- `videotools.py`
- `warn.py`
- `weather.py`
- `webupload.py`
- `words.py`
- `writer.py`
- `youtube.py`
- `ziptools.py`

## How to use with the deployment-only main zip

1. Extract `Ultroid-deployment-only.zip`.
2. Create an `addons/` folder inside the extracted main project.
3. Copy the contents of this Addons package into that `addons/` folder.
4. Copy `project_root_overlay/resources/` into the main project root if you need resource-backed plugins.
5. Set `ADDONS=True`.

The assistant modules were moved into `disabled_assistant_plugins/` with `.disabled` suffixes so they are not loaded accidentally by the recursive addon loader. Rename and move them manually only if you intentionally want to restore assistant-side plugin loading.

Font files are not bundled. Add any required fonts separately if you use addon commands that need them.


## Addons/ folder layout

All runnable addon/plugin Python files now live under `Addons/`. Root files are kept only for repository metadata and dependency installation.
