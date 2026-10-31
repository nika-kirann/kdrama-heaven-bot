# kdrama_heaven bot 💜

An all-in-one Telegram bot for running the **kdrama_heaven** channel: drama cards with posters and status badges, episode buttons, editing posts in place, browse and search, scheduled posts, a daily digest, and auto-cleanup.

> **Content note:** the bot posts **metadata and links only**: poster, title, synopsis, genres, year, status, and the episode links you provide. It never downloads, uploads, or rips video files. **You, the admin, are responsible for only sharing content you have the rights to distribute.**

## Setup
1. **Create the bot:** open [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token.
2. **Make it a channel admin:** in kdrama_heaven, go to *Administrators → Add admin*, pick your bot, and enable **Post messages**, **Edit messages of others**, and **Delete messages of others**.
3. **Get your user id** from [@userinfobot](https://t.me/userinfobot).
4. **Configure:** `cp .env.example .env`, then fill in `BOT_TOKEN`, `CHANNEL_ID` (`@kdrama_heaven`, or the `-100…` id for a private channel), and `ADMIN_IDS`.
5. Open the bot in a DM and press **Start**. The bot can only DM admins (for requests) after you've done this.
6. **Run:**
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   .venv/bin/python main.py        # or simply: ./run.sh
   ```

### Keeping it running 24/7
- Quick option: `nohup ./run.sh > bot.log 2>&1 &` (check it with `tail -f bot.log`).
- Better option: systemd. Edit the paths and user in `kdrama-bot.service`, then run `sudo cp kdrama-bot.service /etc/systemd/system/ && sudo systemctl enable --now kdrama-bot`. It restarts automatically on crashes and reboots.

## Environment variables
| Var | Default | Meaning |
|---|---|---|
| `BOT_TOKEN` | (required) | BotFather token |
| `CHANNEL_ID` | `@kdrama_heaven` | channel @username or -100 id |
| `ADMIN_IDS` | (empty) | comma-separated admin user ids |
| `TIMEZONE` | `Asia/Kolkata` | used for schedules, the digest, and "today" |
| `DAILY_DIGEST_TIME` | `10:00` | daily "New episodes today" post |
| `CLEANUP_DAYS` | `7` | age after which service notices are deleted |
| `CLEANUP_TIME` | `03:30` | daily auto-cleanup time |
| `DATABASE_URL` | `sqlite:///kdrama.db` | SQLAlchemy URL (relative paths resolve to the app dir; Docker uses `/tmp/kdrama.db`) |
| `STORAGE_BACKEND` | `local` | `local` or `telegram` (see Storage backends) |
| `STORAGE_CHANNEL_ID` | `CHANNEL_ID` | private channel holding the DB backup + posters |
| `STORAGE_FLUSH_DELAY` | `3` | seconds of quiet before a backup upload |
| `POSTER_CACHE_DIR` | (off) | optional local poster cache, e.g. `/tmp/posters` |

## Commands
**Admins (in a DM with the bot):**
- `/add`: guided wizard that asks for title, poster (photo or URL), synopsis, genres, year, status (buttons), total episodes, and links. `/skip` leaves a field empty and `/cancel` stops.
  - Links are grouped by **quality** (see "Episode link format" below).
- `/addep <title|id>`: add episodes (numbering continues after the last episode; start with an `EP n` line to add or replace a quality on an existing episode). The channel post is edited in place and a "New episodes" notice is posted. You can also put the links on the lines after the command.
- `/complete <title|id>`: switches the badge to COMPLETED ✅ and announces it.
- `/edit <id> <field> <value>`: fields are title, synopsis, genres, year, poster, total, status, `repost`, `links` (links on the following lines, e.g. `EP 5` then `1080p: https://…`; this replaces only the qualities you give), or `quality <old> <new>` (rename, e.g. `/edit 3 quality 520p 720p`; use `-` as the new name to remove a quality).
- `/delete <title|id>`: deletes the drama and its channel post.
- `/list` (paginated), `/stats`
- `/schedule <title|id|-> YYYY-MM-DD HH:MM <text>`: times are IST. Related: `/schedules`, `/unschedule <id>`.
- `/cleanup`, `/digest` (post the digest now), `/admin` (help)

**Everyone:**
- `/start` and `/browse` open a menu with Search, Latest, Ongoing, Completed, Top genres, and Request drama.
- `/search <title|genre|year>`. Any text sent to the bot in a DM also searches.
- Channel posts have a **Browse episodes** button that shows 10 episodes per page with Prev/Next and Back, plus **Request a drama** and **Search** buttons that open the bot.

## Episode link format
The default qualities are 480p, 720p and 1080p, but any short label works (`4K`, `540p`, `HEVC`…). Inside a quality, **each line is the next episode**, and every quality starts counting from the same first episode (EP 1 in `/add`, or the next new episode in `/addep`).

```
480p: https://ex.com/ep1-480.mp4
720p: https://ex.com/ep1-720-part1.mp4, https://ex.com/ep1-720-part2.mp4
1080p: https://ex.com/ep1.mkv | https://mirror.com/ep1.mkv
```
- Commas separate the **parts** of one episode (shown as `720p Part 1`, `Part 2`).
- ` | ` separates **mirrors** (shown as `Mirror 1`, `Mirror 2`).

You can also write blocks, with a quality on its own line followed by one URL line per episode:
```
720p
https://ex.com/720/1.mp4
https://ex.com/720/2.mp4
```
Patterns can be given per quality, as `pattern start end` (end defaults to total episodes):
```
480p: https://ex.com/480/{ep}.mp4 1 16
1080p: https://ex.com/1080/{ep}.mkv 1 16
```
Add an `EP 9` line to jump to episode 9. Plain URLs with no quality are saved as **HD**, which is also how links saved before qualities existed are treated. They keep working unchanged.

**What viewers see:** an episode with exactly one link opens it straight away. Otherwise, tapping the episode shows a button for each quality it has. A quality with one link opens it directly; a quality with several links shows Part/Mirror buttons. Each screen has a Back button. Viewers stay on the channel post the whole time, because only its buttons are edited in place.

## Notes
- Telegram only lets bots delete channel messages that are **less than 48 hours old**. Older notices that can't be deleted are logged and skipped, and a failed delete of a deleted drama's post is retried by the next cleanup.
- Episode buttons are shared by every viewer of a channel post, so if one person turns the page, everyone sees that page. Each card has a Back button.
- Schedules are stored in SQLite and restored on startup. Any that were missed while the bot was offline are posted right after it starts.

## Tests
`.venv/bin/pytest -q` runs the whole bot against a fake Telegram HTTP layer (`tests/fakes.py`) with a dummy token. No network access is needed.

## Storage backends

| `STORAGE_BACKEND` | What happens |
| --- | --- |
| `local` (default) | Plain SQLite file (`kdrama.db` next to the code). Nothing is uploaded. |
| `telegram` | Same SQLite file, mirrored to a private **storage channel** (`STORAGE_CHANNEL_ID`, falls back to `CHANNEL_ID`). |

How the Telegram backend works:
- **Startup**: before polling starts the bot reads the storage channel's **pinned message**; if it is a `kdrama-backup.db` document it downloads it and opens it. No pin = fresh start, and a first backup is uploaded and pinned right away.
- **Every write**: each DB commit schedules a flush (debounced, `STORAGE_FLUSH_DELAY`, default 3 s; bursts of writes become one upload). The pinned document is replaced in place (`editMessageMedia`); if that fails a new one is sent and pinned and the old one deleted.
- **Shutdown** (SIGTERM / redeploy): a final flush.
- **Posters**: when an admin adds a poster (photo or URL) it is re-sent to the storage channel and its Telegram `file_id` + message id are kept in the DB, so it never depends on the local disk. Optional local cache: `POSTER_CACHE_DIR=/tmp/posters`.
- Limits: Bot API downloads are capped at 20 MB, which is far beyond this DB. Don't unpin or delete the backup message. Run only **one** instance per token.

## Deploy on Koyeb

Koyeb pricing (checked 31 Oct 2026, [koyeb.com/pricing](https://www.koyeb.com/pricing), [instance docs](https://www.koyeb.com/docs/reference/instances)):
- New accounts have **no free plan** any more (the Starter plan was closed in Feb 2026). The entry plan is **Pro, $29/month, including $10 of compute**.
- The free instance (for older orgs) **can't run workers and sleeps after 1 h idle**, so it doesn't fit this bot.
- This bot uses **`eco-nano`** (0.1 vCPU, 256 MB, Singapore): **$1.61/month** always on, covered by the Pro credit. If memory gets tight, use `eco-micro` ($2.68).
- A **worker** service with min scale 1 runs 24/7: it **never sleeps** (no scale-to-zero, no HTTP needed). If the process crashes Koyeb restarts it, and the DB comes back from Telegram.

Steps:
1. **Push to GitHub** (private repo): `git push -u origin main`. `.env` and `*.db` are git-ignored.
2. **Storage channel**: in Telegram create a new *private* channel (e.g. "kdrama storage"), add **@kdrama_help_robot as admin** (post, edit, delete, pin). Get its id (`-100…`): forward a post from it to @userinfobot or @RawDataBot.
3. **Stop the local bot** before Koyeb starts (only one poller per token): `kill -TERM $(pgrep -f "python main.py")`. To carry the current data over, run the local bot once with `STORAGE_BACKEND=telegram` and `STORAGE_CHANNEL_ID=…` so it uploads the backup, then stop it.
4. **Koyeb**: sign up, choose a plan, *Settings → Secrets*, create the secrets `BOT_TOKEN`, `CHANNEL_ID` (`@kdrama_heaven`), `STORAGE_CHANNEL_ID` (`-100…`), `ADMIN_IDS`.
5. **Create the app**: *Create Service → GitHub →* `nika-kirann/kdrama-heaven-bot`, branch `main`, builder **Dockerfile**, service type **Worker**, region **Singapore**, instance **eco-nano**, scaling 1–1. Env vars (secrets are referenced from step 4):

   | Variable | Value |
   | --- | --- |
   | `BOT_TOKEN` | secret `BOT_TOKEN` |
   | `CHANNEL_ID` | secret `CHANNEL_ID` |
   | `STORAGE_CHANNEL_ID` | secret `STORAGE_CHANNEL_ID` |
   | `ADMIN_IDS` | secret `ADMIN_IDS` |
   | `STORAGE_BACKEND` | `telegram` |
   | `TIMEZONE` | `Asia/Kolkata` |
   | `DAILY_DIGEST_TIME` | `10:00` |
   | `CLEANUP_DAYS` | `2` |
   | `CLEANUP_TIME` | `03:30` |

   CLI alternative: install the Koyeb CLI, run `koyeb login`, create the secrets with `koyeb secret create BOT_TOKEN --value '<token>'` (and the same for the others), then run `./deploy-koyeb.sh`. `koyeb.yaml` lists the same settings for reference.
6. **Deploy and read the logs**: *Service → Logs* (or `koyeb service logs kdrama-heaven/bot`). You should see `Telegram storage: restored DB…` or `no backup found… starting fresh`, then `Logged in as @kdrama_help_robot` and `Application started`.
7. **Verify**: send `/start` to the bot, and check that the storage channel has a pinned `kdrama-backup.db`, refreshed a few seconds after each admin change.
8. **Updates**: `git push` to `main` makes Koyeb rebuild and redeploy automatically. The old instance gets SIGTERM, does a final flush, and the new one restores it.
