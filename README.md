---
title: Zelretch
emoji: ✨
colorFrom: purple
colorTo: red
sdk: docker
app_port: 7860
pinned: false
---

# Zelretch

<p align="center">
  <img src="photos/Zelretch.jpg" alt="Zelretch" width="100%">
</p>

<p align="center">
  <b>A MongoDB-backed Telegram userbot with an interactive command center, automatic companion-bot setup, operational logging, and managed addons.</b>
</p>

<p align="center">
  <a href="https://github.com/ChowdhurySiam">GitHub</a> ·
  <a href="https://t.me/Ch0wdhury_Siam">Telegram</a> ·
  <a href="https://github.com/SiamTestingProject/Addons">Addons</a>
</p>

## Project identity

- **Project:** Zelretch
- **Version:** 3.0.0
- **Developer:** [Siam Chowdhury](https://github.com/ChowdhurySiam)
- **Telegram:** [@Ch0wdhury_Siam](https://t.me/Ch0wdhury_Siam)
- **Default prefix:** `.`
- **Runtime:** Python 3.11 + Kurigram
- **Durable database:** MongoDB

## Separate repositories

Zelretch and Zelretch Addons are maintained as separate projects:

- **Zelretch:** deployment core, authorization, MongoDB persistence, command center, logging, and addon loader.
- **Zelretch Addons:** standalone module collection at `https://github.com/SiamTestingProject/Addons`.

The main repository does not bundle addon source files. It downloads and validates them automatically at startup. MongoDB retains the last synchronized addon cache across redeployments.

## Features

- One-time Telegram authorization with the session stored in MongoDB.
- Automatic session restoration after Hugging Face rebuilds or redeployments.
- Automatic companion-bot creation when `BOT_TOKEN` is absent.
- Automatic private operational-log channel creation when `LOG_CHANNEL_ID` is absent.
- Automatic bot invitation and administrator promotion in the logging channel.
- Interactive inline command center with module icons, categories, descriptions, and command usage.
- Automatic Addons synchronization from `https://github.com/SiamTestingProject/Addons`.
- Structured `INFO`, `WARNING`, `ERROR`, and `CRITICAL` operational events.
- Dot prefix enabled by default.
- Light-weight Flask authorization interface for first launch.
- Git LFS/Xet rules for project images.

## Hugging Face deployment

### 1. Create a Docker Space

Create a new Hugging Face Space and select **Docker** as the SDK.

### 2. Push the Zelretch project

Upload the contents of this repository to the Space. Binary images are tracked through Git LFS/Xet.

### 3. Add the required secret

In **Settings → Variables and secrets**, add:

```text
MONGODB_URI=mongodb+srv://USERNAME:PASSWORD@CLUSTER.mongodb.net/zelretch
```

Keep `MONGODB_URI` as a secret.

### 4. Optional Telegram credentials

Zelretch includes fallback Telegram API credentials for compatibility, but using your own is recommended:

```text
API_ID=your_api_id
API_HASH=your_api_hash
```

### 5. Start the Space

On the first deployment, open the Space and complete Telegram authorization once. Zelretch exports the session string to MongoDB. Future deployments using the same database and instance ID restore the account automatically.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---:|---|---|
| `MONGODB_URI` | Yes | — | MongoDB connection string and durable state store. |
| `MONGODB_DATABASE` | No | URI database or `zelretch` | Database name. Existing pre-rebrand databases are detected and migrated. |
| `ZELRETCH_INSTANCE_ID` | No | `default` | Separates multiple accounts in one database. |
| `MONGODB_SYNC_INTERVAL` | No | `15` | Runtime snapshot interval in seconds. |
| `API_ID` | No | Built-in fallback | Telegram API ID. |
| `API_HASH` | No | Built-in fallback | Telegram API hash. |
| `DEVICE_MODEL` | No | `Zelretch` | Telegram device label. |
| `BOT_TOKEN` | No | Automatic | Companion bot for inline help and logging. |
| `LOG_CHANNEL_ID` | No | Automatic | Existing logging channel ID or username. |
| `AUTO_TELEGRAM_SETUP` | No | `true` | Automatically provisions the bot and channel. |
| `AUTO_ADDONS` | No | `true` | Automatically synchronizes the Addons repository. |
| `ADDONS_REPO` | No | `https://github.com/SiamTestingProject/Addons` | Managed addon source. |
| `ADDONS_BRANCH` | No | `main` | Addons branch. |
| `PROJECT_IMAGE_URL` | No | Current Space image | Remote image used by the inline command center. |

`AUTO_TELEGRAM_SETUP=true` and `AUTO_ADDONS=true` are already set in the Docker image. Add them only when overriding the defaults.

## MongoDB-only persistence

MongoDB stores:

- Telegram session string.
- Companion bot token and username.
- Operational logging channel ID.
- Prefix, language, theme, aliases, and sudo-user configuration.
- Triggers and manually managed runtime files.
- Synchronized Addons cache.
- Runtime snapshots through GridFS.

Zelretch 3.0 automatically migrates an existing compatible pre-rebrand state in the same database and instance ID, preserving the saved Telegram session where possible.

## Automatic companion bot and logging channel

Configuration priority:

```text
Environment variables
        ↓
MongoDB service settings
        ↓
Automatic Telegram provisioning
```

When no bot exists, the authorized user account creates one through `@BotFather`, enables inline mode, and stores the token in MongoDB. When no logging channel exists, the account creates a private channel, adds the companion bot, promotes it as administrator, and stores the channel ID.

Expected events:

```text
TELEGRAM_SERVICE_BOOTSTRAP_COMPLETE
LOGGING_CHANNEL_READY
ZELRETCH_STARTUP_COMPLETE
```

## Interactive command center

Send:

```text
.help
```

The companion bot posts the Zelretch project card with inline controls. The command center shows:

- Module icon and clean display name.
- Category.
- Plain-language purpose.
- Available commands and argument format.
- Paginated navigation.
- GitHub and Telegram developer buttons.

## Addons

Addons are enabled automatically from:

```text
https://github.com/SiamTestingProject/Addons
```

The Addons project contains its own README, image, module catalog, metadata, and license. Keep it separate from this deployment-core repository.

To disable automatic synchronization:

```text
AUTO_ADDONS=false
```

## Operational logging

The logging channel receives structured events for:

- Startup, restart, and shutdown.
- Authorization and session restoration.
- Successful connections and connection failures.
- Unexpected disconnects.
- Authentication and session errors.
- Command-processing and Telegram API errors.
- Background synchronization failures.
- Unhandled exceptions, warnings, and critical events.

Secrets and credentials are redacted before delivery.

## Git LFS / Hugging Face Xet

Before pushing from a local Git checkout:

```bash
git lfs install
git add .gitattributes photos/Zelretch.jpg photos/logo.png
git commit -m "Prepare Zelretch deployment"
git push origin main
```

If a rejected binary already exists in Git history:

```bash
git lfs migrate import --include="*.jpg,*.jpeg,*.png,*.gif,*.webp"
git push --force origin main
```

## Local Docker run

```bash
docker build -t zelretch .
docker run --rm -p 7860:7860 \
  -e MONGODB_URI="mongodb+srv://..." \
  zelretch
```

## Security

- Keep the Hugging Face Space private.
- Store MongoDB and Telegram credentials as secrets.
- Restrict MongoDB network access where practical.
- Do not run multiple active deployments with the same Telegram session and `ZELRETCH_INSTANCE_ID`.
- Review third-party Addons before enabling them in sensitive environments.

## License

Zelretch is distributed under the GNU General Public License v3.0. The license file is retained because its terms and notices must remain available with redistributed source.

## Credits

**Developed and maintained by Siam Chowdhury**

- GitHub: `https://github.com/ChowdhurySiam`
- Telegram: `@Ch0wdhury_Siam`
