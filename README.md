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

## Channel card style

New posts and `/edit <id> repost` use the aesthetic card (see `samples/`): title, year, a boxed info panel (Status, Episodes, Audio, Quality, IMDb), genre hashtags, an expandable synopsis and a `Powered by` footer. The main button is **▶️ Browse & Download · N EP**, plus 💌 Request drama and 🔎 Search.
- Dramas without a poster get a generated navy/purple banner (Pillow, bundled DejaVu fonts, text only). It's redrawn when the status or episode count changes. `GENERATE_BANNER=0` turns it off.
- `DEFAULT_AUDIO` (default `Korean, Eng Sub`) and `BRAND` (footer handle, defaults to `CHANNEL_ID` if it's an @username, otherwise `@kdrama_heaven`) are optional env vars.
- `/add` has an optional **Audio** step after Year: `Korean, Eng Sub | 8.2` sets audio and IMDb (or /skip).
- `/edit <id> audio Korean, Hindi Dub` and `/edit <id> imdb 8.4` (`-` clears it).
- Existing posts keep their old look until edited or reposted.

## Private browsing

Channel post keyboards are shared by everyone, so the channel card only ever shows **Browse episodes / Request / Search**. Tapping Browse (or any episode/quality button on a channel post) never edits the post: the bot DMs that viewer their own copy of the card, and all episode → quality → parts/mirrors, Prev/Next and Back taps edit that private message. If the viewer hasn't started the bot yet, the tap opens `t.me/<bot>?start=drama_<id>`, and after /start they get the private card.

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

## Deploy on Koyeb (Free web service + UptimeRobot)

The bot also starts a tiny HTTP server when `PORT` is set (the Dockerfile sets `PORT=8000`; Koyeb passes `PORT` too):
`GET /healthz`, `GET /` (and `HEAD`) return `200 {"ok": true, "uptime_s": …}`; anything else returns 404. Locally `PORT` is unset, so no server starts.

Koyeb's **Free** instance only runs **Web services** (0.1 vCPU, 512 MB, Frankfurt or Washington) and **scales to zero after 1 h without HTTP traffic**. While asleep the bot doesn't poll Telegram. UptimeRobot hitting `/healthz` every 5 minutes keeps it awake. Honest limits:
- Koyeb closed Free/Starter to new sign-ups in Feb 2026. This only works on an organization that still has the free instance.
- If a ping is missed or Koyeb restarts the instance, the bot is offline for a few seconds to a minute, then restores the DB from the storage channel.
- Paid alternative with no pinger needed: Worker, `eco-nano`, Singapore, $1.61/month (Pro plan required).

Steps:
1. **Storage channel**: private channel, **@kdrama_help_robot as admin** (post/edit/delete/pin). Its id goes in `STORAGE_CHANNEL_ID` (already seeded: `-1004241251090`).
2. **Only one instance per token.** Keep the local bot stopped.
3. **Koyeb → Secrets**: `BOT_TOKEN`, `CHANNEL_ID` (`@kdrama_heaven`), `STORAGE_CHANNEL_ID`, `ADMIN_IDS`.
4. **Create Service → Web service → GitHub** `nika-kirann/kdrama-heaven-bot`, branch `main`, builder **Dockerfile**, instance **Free**, region **Frankfurt**.
   - Port **8000 / HTTP**, route `/`.
   - Health check: HTTP `/healthz` on 8000.
   - Env vars:

   | Variable | Value |
   | --- | --- |
   | `BOT_TOKEN` | secret `BOT_TOKEN` (paste your bot token) |
   | `CHANNEL_ID` | secret `CHANNEL_ID` |
   | `STORAGE_CHANNEL_ID` | secret `STORAGE_CHANNEL_ID` |
   | `ADMIN_IDS` | secret `ADMIN_IDS` |
   | `PORT` | `8000` |
   | `STORAGE_BACKEND` | `telegram` |
   | `TIMEZONE` | `Asia/Kolkata` |
   | `DAILY_DIGEST_TIME` | `10:00` |
   | `CLEANUP_DAYS` | `2` |
   | `CLEANUP_TIME` | `03:30` |

   CLI alternative: `koyeb login`, create the secrets with `koyeb secret create NAME --value '…'`, then run `./deploy-koyeb.sh`. `koyeb.yaml` mirrors the same settings.
5. **Deploy and check the logs**: you should see `Health server listening on 0.0.0.0:8000`, `restored DB from message …`, `Logged in as @kdrama_help_robot`, `Application started`. Then open `https://<app>-<org>.koyeb.app/healthz` and check it returns `{"ok": true, …}`.
6. **UptimeRobot** (free account at uptimerobot.com) → *Add New Monitor*:
   - Monitor type **HTTP(s)**
   - Friendly name `kdrama bot`
   - URL `https://<your-app>.koyeb.app/healthz`
   - Interval **5 minutes** (the free minimum)
   - Timeout 30 s
   - Alert contact: your email/Telegram
   - Optional: keyword monitor on `"ok": true`

   UptimeRobot alerts you if it stops returning 200.
7. **Updates**: `git push` to `main` redeploys automatically (old instance: SIGTERM → final backup flush; new instance restores it).
