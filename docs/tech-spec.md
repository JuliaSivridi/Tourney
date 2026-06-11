# Tourney — Technical Specification

---

## 1. Overview

Tourney is a single-user Telegram tournament bot. Each Telegram user gets a private tournament session — there is no concept of shared rooms or spectators. The bot supports three bracket formats (Single Elimination, Double Elimination, Round Robin) and exposes two surfaces for interaction:

- **Inline mode** — a live-updated InlineKeyboard message inside the Telegram chat. The user taps a player name to record a win; the message edits in place after every result.
- **Mini App (web)** — a Telegram WebApp served from the same Docker container as the bot. The app provides a visual bracket canvas, a standings table, undo, and a "New tournament" flow from scratch.

Both surfaces are fully synchronized: starting or advancing a match via either surface updates the shared PostgreSQL state, and a background refresh timer (4 000 ms) in the Mini App polls the server for updates.

**Key design decisions:**

| Decision | Rationale |
|---|---|
| Single JSON column for all bracket state | No join tables; entire bracket can be read and written in one query. Mirrors the original PHP design. |
| Same process hosts bot + HTTP server | Minimizes infrastructure — one container, one port (8003), no side-car. |
| `create_all` at startup, no migrations | Simplicity for a single-developer pet project; `alembic` is in `requirements.txt` but no migration files exist. |
| Absolute-position JS layout engine | Allows pixel-precise bracket connectors without a charting library. |
| Server-computed `ranking` in API responses | Ensures DE grand-final winner/loser order is consistent between web and Telegram chat. |

**Repository:** https://github.com/JuliaSivridi/Tourney

---

## 2. Tech Stack

| Layer | Library | Version | Notes |
|---|---|---|---|
| Bot framework | aiogram | 3.13.1 | Asyncio-native; FSM via `MemoryStorage` |
| HTTP server | aiohttp | >=3.9.0, <3.11 | Serves Mini App static files + REST API |
| Database driver | asyncpg | 0.29.0 | Native async PostgreSQL |
| ORM | SQLAlchemy\[asyncio\] | 2.0.36 | `async_sessionmaker`, `expire_on_commit=False` |
| Migrations tooling | alembic | 1.14.0 | Installed but unused; schema created via `create_all` |
| Config | python-dotenv | 1.0.1 | Loads `.env` file |
| Database | PostgreSQL | 16-alpine (Docker) | Single table per-user design |
| Runtime | Python | 3.12-slim (Docker) | `python:3.12-slim` base image |

---

## 3. Architecture

### 3.1 Pattern

The server side follows a **handler → engine → database** pattern with no dedicated ViewModel layer. Business logic lives in `bracket_engine.py` (pure functions, no I/O). Handlers call the engine and persist the result in one SQLAlchemy session.

### 3.2 Data-flow diagram

```
Telegram ──────────┐
 (callback_query)  │
                   ▼
            aiogram Dispatcher
              (FSM + routers)
                   │
         ┌─────────▼──────────┐
         │  handler (*.py)    │
         │  reads GameState   │
         │  calls eng.*()     │
         │  writes GameState  │
         └─────────┬──────────┘
                   │  SQLAlchemy async session
                   ▼
             PostgreSQL
                   │
                   │  (same write path for web)
                   ▼
            aiohttp REST API  ◄──── Mini App (browser)
            (main.py api_*)         fetch("/api/game/…")
```

### 3.3 Write path (example: user taps a player in Mini App)

1. Browser `POST /api/game/{uid}/match` with `{m_idx, winner_slot}`.
2. `api_match` opens an `AsyncSessionLocal` session, loads `GameState` row for `uid`.
3. Calls `eng.loads(gs.state_json)` → Python dict.
4. Validates match is ready (both slots are `dict`-type).
5. Calls `eng.apply_result(state, m_idx, winner_slot, fmt)` → new state (deep copy, no mutation).
6. Serialises new state: `gs.state_json = eng.dumps(new_state)`.
7. Checks `eng.is_finished(state, fmt)` → sets `gs.status = "finished"` if true.
8. `await session.commit()`.
9. Calls `_sync_inline_finished` or `_sync_inline` to update the Telegram message via `bot.edit_message_text` / `bot.send_message`.
10. Calls `_assign_rounds` to enrich matches with `round` and `section` fields.
11. Returns JSON response including `players`, `matches`, `ranking`, `format`, `finished`.

### 3.4 Read path (Mini App on load)

1. Browser `GET /api/game/{uid}`.
2. `api_get` loads `GameState` from DB.
3. Calls `eng.loads`, `_assign_rounds`, `eng.sorted_results`.
4. Returns full state JSON (status, format, players, matches with round/section, last_m, ranking).
5. JS `route(data)` switches to the correct screen; `renderGame` → `renderBracket` + `renderStandings`.

### 3.5 Error handling strategy

- API handlers return HTTP 400 for missing/invalid input; 404 if no `GameState` row exists for the uid.
- `_sync_inline`, `_sync_inline_finished`, `_create_inline_for_web` all catch all exceptions and log at DEBUG level — Telegram sync failures never abort the primary API response.
- `api_match`: if the target match is not ready (slots not filled), returns `{"ok": false, "error": "match not ready"}` — JS guards on `data.ok && data.matches` before re-rendering.
- Bot handlers catch exceptions in `handle_match_pick` and send an `⚠️ Error:` message to the user.

---

## 4. Package / Folder Structure

```
Tourney/
├── bot/                       # Python package — entire server-side
│   ├── __init__.py
│   ├── main.py                # Entry point: aiohttp app + aiogram Dispatcher startup
│   ├── config.py              # Env var loading (BOT_TOKEN, WEBAPP_URL, DB creds)
│   ├── states.py              # aiogram FSM state groups
│   ├── middleware.py          # DbSessionMiddleware — injects DB session into handlers
│   ├── bracket_engine.py      # Pure bracket logic: init_se/de/rr, apply_result,
│   │                          #   undo_result, sorted_results, build_results_lines
│   ├── db/
│   │   ├── __init__.py
│   │   ├── engine.py          # SQLAlchemy async engine, AsyncSessionLocal, init_db()
│   │   └── models.py          # User, GameState ORM models; TournamentFormat/Status enums
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── start.py           # /start, /help, /lang, /cancel commands
│   │   ├── tournament.py      # /newgame, format selection, player-list keyboard
│   │   ├── players.py         # Player name input, shuffle/cancel/start callbacks
│   │   └── matches.py         # build_keyboard, handle_match_pick, _show_results
│   ├── formats/               # LEGACY — not imported anywhere in the current codebase.
│   │   ├── __init__.py        #   References Match/Player models that no longer exist in
│   │   ├── single_elim.py     #   models.py. Predates the JSON bracket_engine approach.
│   │   ├── double_elim.py
│   │   └── round_robin.py
│   └── locales/
│       ├── __init__.py
│       ├── i18n.py            # t(), normalize_lang(), flags_keyboard(), lang_from_flag_btn()
│       ├── en.json            # English strings
│       ├── ru.json            # Russian strings
│       ├── de.json            # German strings
│       ├── fr.json            # French strings
│       ├── pt-br.json         # Portuguese (Brazil) strings
│       └── uk.json            # Ukrainian strings
├── docs/                      # Mini App static files (served by aiohttp)
│   ├── index.html             # SPA shell — 5 screen divs, no framework
│   ├── app.js                 # All client logic: routing, bracket renderer, API calls
│   └── style.css              # CSS custom properties, dark/light themes, bracket layout
├── _docs/
│   ├── tech-spec-example.css  # CSS template for this document
│   ├── tech-spec.md           # ← this file
│   └── tech-spec.html         # Rendered HTML version
├── Dockerfile                 # python:3.12-slim, copies bot/ and docs/, CMD python -m bot.main
├── docker-compose.yml         # Services: bot (port 8003) + db (postgres:16-alpine, volume pgdata)
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variable template
└── README.md                  # Russian-language README
```

> **Note:** `bot/formats/` files are dead code. They reference `Match` and `Player` ORM classes that do not exist in `bot/db/models.py`. The current architecture stores all bracket data as JSON in `GameState.state_json` via `bracket_engine.py`.

---

## 5. Data Model

### 5.1 `TournamentFormat` enum (stored as string)

| Value | Meaning |
|---|---|
| `"single_elim"` | Single Elimination |
| `"double_elim"` | Double Elimination |
| `"round_robin"` | Round Robin |

### 5.2 `TournamentStatus` enum (stored as string)

| Value | Meaning |
|---|---|
| `"idle"` | No active game; row exists but tournament not started |
| `"setup"` | Format selected, collecting player names (inline mode only) |
| `"active"` | Matches in progress |
| `"finished"` | Tournament complete; results available |

### 5.3 `User` entity

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | BigInteger | PRIMARY KEY | Telegram `chat.id` |
| `user_name` | String(256) | NOT NULL | Full name from Telegram (`first_name + last_name`) |
| `lang` | String(8) | DEFAULT `"en"` | UI language code; one of the 6 supported values |

### 5.4 `GameState` entity

| Field | Type | Constraints | Description |
|---|---|---|---|
| `user_id` | BigInteger | PRIMARY KEY | FK → users.id (by convention; no DB constraint) |
| `format` | String(32) | DEFAULT `""` | Tournament format string (`"single_elim"` etc.) or empty |
| `title` | String(256) | DEFAULT `""` | Tournament name; set but not currently displayed |
| `status` | String(16) | DEFAULT `"idle"` | Tournament status string |
| `kbd_message_id` | BigInteger | DEFAULT `0` | Telegram message_id of the inline keyboard message; `0` = no message sent yet |
| `state_json` | Text | DEFAULT `"{}"` | Full bracket state JSON (see §5.5) |

### 5.5 `state_json` schema

The `state_json` column stores the complete bracket state as a JSON string. Structure:

```json
{
  "players": [
    { "name": "string", "losses": 0, "played": 0 }
  ],
  "matches": [
    {
      "grid": true,
      "p": [
        { "id": 0, "name": "Alice", "state": 0, "next": [] },
        { "id": 1, "name": "Bob",   "state": 0, "next": [3, 0] }
      ]
    }
  ],
  "last_m": -1,
  "last_p": -1
}
```

**Field definitions:**

| Field | Type | Description |
|---|---|---|
| `players[].name` | string | Display name |
| `players[].losses` | int | Number of losses; ≥2 → eliminated in DE |
| `players[].played` | int | Matches played; wins = played − losses |
| `matches[].grid` | bool or null | `true`=winners bracket, `false`=losers bracket, `null`=not yet assigned (grand final awaiting) |
| `matches[].p[0/1]` | slot or null | `null` = slot not yet filled (future match) |
| `slot.id` | int | Index into `players` array |
| `slot.state` | int | 0=pending, 1=winner, 2=loser (alive in DE), 3=eliminated |
| `slot.next` | `[m, p]` or `[]` | Index of next match and slot position this player advances to |
| `last_m` | int | Index of the last decided match; `-1` if none |
| `last_p` | int | Slot index of the loser in the last match; used for undo highlight in Telegram keyboard |

**During web setup only** (between `/format` and `/start` API calls), `state_json` may also contain:

```json
{ "players_pending": ["Alice", "Bob", "Carl"] }
```

This list is consumed by `api_start` to initialise the bracket.

**Important invariants:**
- `players[i].losses < 2` = alive in DE; `< 1` = alive in SE/RR.
- `matches[].p` has exactly 2 elements (always a pair), but either may be `null`.
- After `apply_result`, the loser's `slot.next` points to their destination match in the losers bracket (DE only) — not yet to a future slot, since slots are filled lazily by `_move_player_de`.
- `undo_result` removes the winner and loser from their `next` match by setting `matches[nm]["p"][np] = None`.

---

## 6. Database / Storage Schema

### 6.1 Tables

#### `users`

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | BIGINT | NOT NULL | — | PK; Telegram chat_id |
| `user_name` | VARCHAR(256) | NOT NULL | — | |
| `lang` | VARCHAR(8) | NOT NULL | `'en'` | Language code |

#### `game_state`

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `user_id` | BIGINT | NOT NULL | — | PK; one row per user |
| `format` | VARCHAR(32) | NOT NULL | `''` | Empty string when unset |
| `title` | VARCHAR(256) | NOT NULL | `''` | |
| `status` | VARCHAR(16) | NOT NULL | `'idle'` | |
| `kbd_message_id` | BIGINT | NOT NULL | `0` | 0 = no keyboard message |
| `state_json` | TEXT | NOT NULL | `'{}'` | Full bracket JSON |

### 6.2 Schema version and migrations

There is no Alembic migration history. On every container startup, `init_db()` calls `Base.metadata.create_all(engine)`. This is a no-op if tables already exist; no destructive ALTER is applied. If a column is added in code, it will **not** be added to an existing database — a manual migration or `DROP TABLE` + restart is required.

### 6.3 Conventions

- No soft-delete: `/newgame` resets the `GameState` row in-place (all fields overwritten to defaults).
- No separate match/player/round tables — all bracket data lives in the single `state_json` text column.
- `expire_on_commit=False` is set on `AsyncSessionLocal` — attributes do not expire after commit; previously-captured Python values remain valid.

---

## 7. Authentication & First-Launch Setup

There is no authentication layer. Users are identified by their Telegram `chat.id` only. The Mini App passes `uid` as a URL query parameter (`?uid={chat_id}`), derived from either the URL or `tg.initDataUnsafe.user.id` on the client side. There is no server-side validation of the uid beyond checking it is a digit string.

### First-launch flow (inline mode)

1. User sends `/start` to the bot.
2. `cmd_start` calls `get_or_create_user(session, message)`.
3. If no `User` row exists: reads `message.from_user.language_code`, calls `normalize_lang()` to map to a supported locale code (prefix match; falls back to `"en"`). Creates `User` and an empty `GameState(user_id=chat_id)` in the same session and commits.
4. Bot replies with `t(lang, "hi", name=first_name)`.

### First-launch flow (Mini App)

1. User opens the Mini App without having used the bot.
2. JS reads `uid` from URL or `tg.initDataUnsafe.user.id`.
3. `GET /api/game/{uid}` → if no `GameState` row, returns `{"status": "idle", "format": "", "players": [], "matches": []}`.
4. JS `route(data)` → `!data.format` → calls `resetToFormat()` → shows `screen-format`.
5. No `User` row is created until the user starts the bot inline (`/start`). The Mini App can create a `GameState` row via the POST endpoints (e.g. `api_new` calls `GameState(user_id=uid)` if none exists), but `User` is only created through `/start`.

---

## 8. Synchronization / API Layer

### 8.1 REST API endpoints

All endpoints under `/api/game/{uid}`. CORS headers (`Access-Control-Allow-Origin: *`) are added to every response.

| Method | Path | Body | Response | Notes |
|---|---|---|---|---|
| GET | `/api/game/{uid}` | — | `{status, format, players, matches, last_m, ranking}` | Always returns current state; `ranking` always computed if matches exist |
| POST | `/api/game/{uid}/new` | — | `{"ok": true}` | Resets GameState to defaults; also removes webapp button from old keyboard message |
| POST | `/api/game/{uid}/format` | `{"format": "single_elim"}` | `{"ok": true}` | Validates against 3 known values; 400 otherwise |
| POST | `/api/game/{uid}/players` | `{"players": ["A","B",...]}` | `{"ok": true, "players": [...]}` | Stores as `players_pending` in state_json; min 2 required |
| POST | `/api/game/{uid}/start` | — | `{ok, format, status, players, matches, last_m}` | Initialises bracket; triggers `_create_inline_for_web` if `kbd_message_id == 0` |
| POST | `/api/game/{uid}/match` | `{"m_idx": 0, "winner_slot": 1}` | `{ok, format, finished, ranking, status, players, matches, last_m}` | Returns `{"ok": false}` if match not ready |
| POST | `/api/game/{uid}/undo` | `{"m_idx": 0}` | `{ok, format, players, matches, last_m}` | Resets status to "active" |
| OPTIONS | `/api/game/{uid}/{tail:.*}` | — | Empty 200 | CORS preflight |

### 8.2 `matches` field enrichment (`_assign_rounds`)

Every API response that returns `matches` passes them through `_assign_rounds(match_list, fmt, n_players)` which adds two fields to each match dict:

| Added field | Type | Description |
|---|---|---|
| `round` | int | Round number (1-based) within its section |
| `section` | string | `"winners"`, `"losers"` (DE losers bracket), or `"rr"` |

**SE round assignment:** iterates `n_players → n_players//2 → … → 1`, allocating `rem//2` matches to each round.

**DE round assignment:**
- Winners: same halving as SE, applied to matches where `grid=True`.
- Losers: pairs of consecutive `grid=False` matches share a round (`j//2 + 1`).
- Grand final (`grid=None`): assigned `max_winners_round + 1`, section `"winners"`.

**RR round assignment:** `n_players//2` matches per round (Berger schedule produces exactly `n-1` rounds with `n//2` matches each for even `n`).

### 8.3 Telegram sync helpers

| Function | Trigger | Action |
|---|---|---|
| `_create_inline_for_web` | `api_start` when `kbd_message_id == 0` | Sends a new inline keyboard message to the user's chat; saves `message_id` to DB in a second session |
| `_sync_inline` | `api_match` (not finished), `api_undo` | Edits the existing inline keyboard message text + reply markup |
| `_sync_inline_finished` | `api_match` (finished) | Edits keyboard to remove webapp button; sends a separate results message |

All three functions catch all exceptions and log at DEBUG level — sync failures are non-fatal.

### 8.4 Offline / polling behavior

The Mini App polls `GET /api/game/{uid}` every 4 000 ms via `setInterval` while `screen-game` is active. The timer is cleared when navigating away or when a tournament finishes. There is no WebSocket or push mechanism; the inline Telegram message is the bot's push channel.

---

## 9. UI Screens (Mini App)

### 9.1 Screen: Format Selection (`screen-format`)

**Trigger:** shown when `uid` is absent, or `data.format` is empty/falsy after polling.

**Elements:** Three `.format-btn` buttons with `data-fmt` attributes:
- `data-fmt="single_elim"` — icon 🏆, name "Single Elimination", desc "Выбыл — значит выбыл"
- `data-fmt="double_elim"` — icon 🔁, name "Double Elimination", desc "Дают второй шанс"
- `data-fmt="round_robin"` — icon 🔄, name "Round Robin", desc "Каждый с каждым"

**Action on click:**
1. `POST /api/game/{uid}/new` (resets any existing tournament)
2. `POST /api/game/{uid}/format` with selected format
3. Shows `screen-players`

If `uid` is null, shows an `alert("Открой через Telegram бот")` and does nothing.

---

### 9.2 Screen: Players (`screen-players`)

**Elements:**
- `<textarea id="players-input">` — multi-line; placeholder shows example names (Алиса, Борис, Катя, Дима)
- `btn-shuffle` — Fisher-Yates shuffle of current textarea lines (client-side only)
- `btn-start` — validates ≥2 names, posts to API
- `back-from-players` — resets to format screen

**Helper `getPlayerLines()`:** splits textarea by `\n`, trims each, filters empty strings.

**Action on "Начать турнир →":**
1. Reads names via `getPlayerLines()`.
2. `POST /api/game/{uid}/players` with `{players: names}`.
3. `POST /api/game/{uid}/start`.
4. Calls `renderGame(data)` with the start response.
5. Shows `screen-game`; starts 4 000 ms refresh timer.

---

### 9.3 Screen: Game (`screen-game`)

**Header:** format label (text from `FMT_LABEL` map) + "Новый турнир" button.

**Tabs:**
- **Матчи** (`matches-view`) — bracket canvas
- **Таблица** (`standings-view`) — standings table

**Standings table** (`#standings-table`): columns `#`, Игрок, 🏆 (wins), 💀 (losses), ⚡ (played). Sorted by `sortedPlayers()` (wins desc, losses asc) — note: this is a simple sort; it does not use the server `ranking` field (which is only used in the results screen).

**Bracket change detection (`_bracketKey`):**
```
key = last_m + "|" + matches.map(m => p[0].state + p[1].state).join(",")
```
`renderBracket` is skipped if key equals `_lastBracketKey`. `renderStandings` always runs.

**"Новый турнир" button:** confirms with `confirm()`, stops timer, posts `/new`, resets to format screen.

---

### 9.4 Screen: Results (`screen-results`)

**Elements:** `.results-title` ("🏆 Результаты"), `#results-list` (result rows), "Новый турнир" button.

**Ranking logic:**
- Uses `data.ranking` (server-computed list of player-index groups) if present.
- Falls back to `clientSideGroups(players)` if `ranking` is absent.
- **Dense ranking:** `place += 1` per group regardless of tie size (1,2,3,4… even with ties).
- Medals: `["🥇","🥈","🥉"]` for places 0–2; `#N` for places ≥3.

**Trigger:** `pickWinner` sets a 500 ms `setTimeout` before showing results, to allow the last-match UI to briefly update.

---

### 9.5 Screen: Loading (`screen-loading`)

Shown immediately on `init()`. Displays a single `⏳` emoji centered on the screen. Replaced by the appropriate screen once `GET /api/game/{uid}` resolves.

---

## 10. Key Components

### 10.1 `buildBracket(matches, last_m, drawConnectors, maxRound, isLosers, isDE)` (JS)

Absolute-position bracket layout engine.

**Parameters:**

| Name | Type | Description |
|---|---|---|
| `matches` | array | Filtered match objects with `round`, `section`, `p`, `origIdx` |
| `last_m` | int | Index of last decided match (for undo button) |
| `drawConnectors` | bool | `true` for SE (lines drawn); `false` for DE (omitted) |
| `maxRound` | int | Highest round number in this section (for label names) |
| `isLosers` | bool | `true` for DE losers section |
| `isDE` | bool | `true` for DE winners section |

**Layout constants:**
- `COL_W = 170` px — match card width
- `CONN_W = 32` px — gap between columns
- `CARD_H = 82` px — match card height (2×40 px rows + borders)
- `SLOT_PAD = 10` px — padding above/below each card in its vertical slot

**Layout algorithm:**
```
r1Count = matches in round 1
totalH  = r1Count × (CARD_H + SLOT_PAD × 2)
totalW  = nRounds × COL_W + (nRounds − 1) × CONN_W
for each round r (index ri):
  slotH = totalH / count_in_round_r
  for each match mi in round r:
    centerY = slotH × mi + slotH / 2
    cardTop = round(centerY − CARD_H / 2)
    card placed at: left = ri × (COL_W + CONN_W), top = cardTop, width = COL_W
```

**Returns:** a `<div class="bracket-scroll">` wrapping a `<div class="bracket-wrap">`. The scroll wrapper has `overflow-x: auto` to contain absolute-positioned children.

**Connector lines (SE only):** drawn as `<div class="conn-line">` (2 px thick). A full connector (horizontal arm from match 0, horizontal arm from match 1, vertical bar, horizontal arm to next) is drawn only when **both** pair matches are decided. A bye connector (solo match) is drawn only when that match is decided.

---

### 10.2 `makeMatchCard(match, last_m)` (JS)

Builds a `<div class="match-card">` DOM node.

**Match number label:** `#01`-format, 1-based, top-right, using `match.origIdx ?? match.idx ?? 0`.

**Player rows:** one `.match-player` div per slot.
- State CSS classes: `""` (pending), `"winner"`, `"loser"`, `"elim"`.
- `"clickable"` added if both slots present and match not yet decided.
- Click handler calls `pickWinner(origIdx, slotIndex)`.
- If `decided && origIdx === last_m`: adds an `.undo-btn` (`↺`, 20 px, accent colour, 36×36 px tap target) to the row.
- Bye slot (null): renders empty name with dimmed `⚪` icon.

---

### 10.3 `build_keyboard(state, user_id, lang, show_webapp=True)` (Python)

Builds the Telegram `InlineKeyboardMarkup` for the match list.

**Per-match row** (only for matches where both slots are filled):
```
[🟩#01]  [⚪ Alice]  [⚪ Bob]
```
- Column 1: `{grid_icon}#{m_idx:02d}` — grid icon is 🟩 (`grid=True`) or 🟥 (`grid=False` / losers). Callback: `m:{m_idx}:x` (no-op).
- Column 2/3: `{state_icon} {name}` — state icons: `⚪` (0), `🟢` (1), `🔴` (2), `⚫` (3).

**Callback data assignment logic (per slot):**
1. If `m_idx == last_m AND slot == last_p_l` → `m:{m_idx}:{slot}:replay` (triggers undo).
2. Else if `already_decided` → `m:{m_idx}:x` (no action).
3. Else if `player.state == 0` → `m:{m_idx}:{slot}:pick` (pick winner).
4. Else → `m:{m_idx}:x`.

**WebApp button:** appended if `show_webapp=True` AND `WEBAPP_URL.startswith("https://")`. URL: `{WEBAPP_URL}?uid={user_id}`.

---

### 10.4 `DbSessionMiddleware` (Python)

`BaseMiddleware` for aiogram. Opens an `AsyncSessionLocal` context for every incoming `Message` and `CallbackQuery` event. Injects the session as `data["session"]`, available in all handlers as `session: AsyncSession`.

---

### 10.5 `t(lang, key, **kwargs)` (Python)

Translation helper. Loads locale JSON from `bot/locales/{lang}.json` (cached in `_cache` dict after first load). Falls back to `_DEFAULT="en"` if `lang` not in `_SUPPORTED`. Applies `.format(**kwargs)` for string interpolation.

**Supported locale codes:** `"en"`, `"de"`, `"fr"`, `"pt-br"`, `"uk"`, `"ru"`.

---

## 11. Theme & Colors

The Mini App implements automatic dark/light theming via CSS custom properties.

### 11.1 CSS custom properties

| Variable | Dark value | Light value | Usage |
|---|---|---|---|
| `--bg` | `#242424` | `#f2f2f7` | Page background |
| `--surface` | `#2e2e2e` | `#ffffff` | Cards, inputs, table |
| `--surf2` | `#3a3a3a` | `#e5e5ea` | Hover states, secondary buttons |
| `--border` | `#4d4d4d` | `#c8c8cd` | Borders, connector lines |
| `--accent` | `#0a84ff` | `#007aff` | Buttons, active tabs, links |
| `--green` | `#30d158` | `#34c759` | Winners bracket section, winner row tint |
| `--red` | `#ff453a` | `#ff3b30` | Losers bracket section, loser row tint |
| `--text` | `#efefef` | `#1c1c1e` | Body text |
| `--muted` | `#909090` | `#6c6c70` | Hints, round labels, match numbers |
| `--r` | `10px` | `10px` | Standard border-radius |
| `--rs` | `7px` | `7px` | Small border-radius (cards, buttons) |

### 11.2 Theme detection

Light theme is activated in two ways:
1. **Telegram WebApp**: on startup, `if (tg.colorScheme === "light")` adds class `light-theme` to `<html>`.
2. **Browser preview**: CSS `@media (prefers-color-scheme: light)` on `:root:not(.dark-theme)`.

### 11.3 DE section colors

Winners section background: `rgba(48, 209, 88, 0.12)` dark / `rgba(48, 209, 88, 0.15)` light.  
Winners section border: `rgba(48, 209, 88, 0.35)` dark / `rgba(48, 209, 88, 0.45)` light.  
Losers section background: `rgba(255, 69, 58, 0.10)` dark / `rgba(255, 69, 58, 0.13)` light.  
Losers section border: `rgba(255, 69, 58, 0.32)` dark / `rgba(255, 69, 58, 0.40)` light.

---

## 12. Navigation & Deeplinks

### 12.1 Telegram bot commands

| Command | Handler | Action |
|---|---|---|
| `/start` | `cmd_start` | Greet; create User + GameState rows on first use |
| `/help` | `cmd_help` | Send help text listing commands |
| `/lang` | `cmd_lang` | Show language selection keyboard |
| `/newgame` | `cmd_newgame` | Reset GameState; enter `TournamentSetup.choosing_format` |
| `/cancel` | `cmd_cancel` | Clear FSM state; reply "Cancelled" |

### 12.2 Mini App URL

The Mini App is opened via the Telegram menu button or an inline keyboard `WebAppInfo` button:

```
https://{WEBAPP_URL}?uid={chat_id}
```

- `uid` is the Telegram `chat.id` of the user.
- No other URL parameters are used.
- The app also reads uid from `tg.initDataUnsafe.user.id` as a fallback.

### 12.3 FSM state transitions

```
(new user)
     │
     ▼
[no FSM state]  ──/newgame──►  TournamentSetup.choosing_format
                                        │
                               (click format button)
                                        │
                                        ▼
                               TournamentSetup.adding_players
                                        │
                               (click "Start tournament")
                                        │
                                        ▼
                               TournamentActive.playing
                                        │
                               (tournament finished, or /cancel)
                                        │
                                        ▼
                                  [state cleared]
```

---

## 13. Loading & Empty States

### 13.1 Loading

`screen-loading` shows a single `⏳` emoji (`font-size: 32px`) centered on the screen. It is the initially visible screen; `init()` replaces it immediately upon receiving the first `GET /api/game/{uid}` response.

### 13.2 Empty states in bracket

| Condition | HTML rendered |
|---|---|
| `matches` array empty | `<div class="empty">Матчей пока нет</div>` |
| All matches have no filled slots | `<div class="empty">Ожидание участников...</div>` |

`.empty` class: `text-align: center; color: var(--muted); padding: 40px 16px; font-size: 14px`.

### 13.3 Match placeholder

A match with `grid=True` but one slot unfilled (bye slot) renders the missing slot as:
```html
<span class="slot-icon" style="opacity:.3">⚪</span>
<span class="slot-name"></span>
```
(no name text, dimmed icon)

---

## 14. CI/CD & Build

There is no CI/CD pipeline. The project has no `.github/workflows/` directory.

**Local build and deploy:**
```bash
git pull
docker compose up -d --build   # rebuilds the bot image and restarts
docker compose logs -f         # monitor logs
```

**What the Dockerfile does:**
1. Base: `python:3.12-slim`
2. `WORKDIR /app`
3. `COPY requirements.txt .` → `pip install --no-cache-dir -r requirements.txt`
4. `COPY bot/ ./bot/` and `COPY docs/ ./docs/`
5. `CMD ["python", "-m", "bot.main"]`

Note: `docs/` is copied into the container image. Static file updates require a rebuild and restart.

---

## 15. First-Time Setup (New Developer)

1. **Clone the repository:**
   ```bash
   git clone git@github.com:JuliaSivridi/Tourney.git
   cd Tourney
   ```

2. **Create `.env` from template:**
   ```bash
   cp .env.example .env
   # Edit .env and set:
   #   BOT_TOKEN=<your bot token from @BotFather>
   #   POSTGRES_PASSWORD=<any password>
   #   WEBAPP_URL=https://<your domain>   # must be HTTPS for WebApp button
   #   WEBAPP_PORT=8003
   ```

3. **Create Telegram bot:** Talk to [@BotFather](https://t.me/BotFather), use `/newbot`, copy the token into `.env`.

4. **Configure nginx** to proxy the API and serve the Mini App over HTTPS:
   ```nginx
   location /tourney-api/ {
       proxy_pass http://127.0.0.1:8003/;
       proxy_set_header Host $host;
   }
   ```
   (The app itself does not terminate TLS; nginx handles HTTPS.)

5. **Start containers:**
   ```bash
   docker compose up -d --build
   docker compose logs -f
   ```
   The `bot` service waits for `db` to be healthy (pg_isready, 5 s interval, 10 retries).

6. **Register Mini App with BotFather:**
   - `/mybots` → select your bot → **Bot Settings** → **Menu Button**
   - Set URL to `https://<your domain>`

7. **Verify:** send `/start` to the bot; open the Mini App via the menu button.

---

## 16. Key Algorithms

### 16.1 SE bracket initialisation (`init_se`)

```
players = [{"name": n, "losses": 0, "played": 0} for n in player_names]
matches = N × {grid: None, p: [null, null]}

for each player p in 0..N-1:
    for each match m in matches:
        if slot 0 is empty:  place p in slot 0; break
        if slot 1 is empty:  place p in slot 1; break
```

Players fill matches left-to-right sequentially. No seeding — order determined by the input list.

### 16.2 DE bracket initialisation (`init_de`)

```
players = [{"name": n, "losses": 0, "played": 0} for n in player_names]
matches = (2N-1) × {grid: None, p: [null, null]}

for each player p in 0..N-1:
    for each match m in matches:
        if m.grid is None: m.grid = True  (first assignment)
        if m.grid == True and has empty slot:
            place p; break
```

### 16.3 RR bracket initialisation (`init_rr`) — Berger circle method

```
if N is odd: append None (bye) to names list
n = len(names)
fixed = names[0]
rotating = names[1:]

for round in 0..n-2:
    pairs = [(fixed, rotating[0])]
           + [(rotating[i], rotating[n-1-i]) for i in 1..n//2-1]
    for (p1, p2) in pairs:
        if neither is None: create match (p1, p2)
    rotating = rotating[1:] + [rotating[0]]   # rotate left by 1
```

This produces exactly `n-1` rounds, `n//2` matches per round (for even `n`).

### 16.4 `apply_result`

```
state = deepcopy(state)
winner_p = match.p[winner_slot].id
loser_p  = match.p[loser_slot].id

players[winner_p].played += 1
players[loser_p].played  += 1
players[loser_p].losses  += 1

match.p[winner_slot].state = 1 (winner)
loser_state = 2 if players[loser_p].losses < (2 if DE else 1) else 3
match.p[loser_slot].state = loser_state

if SE or RR:
    move winner to next SE match
elif DE:
    alive = count of players with losses < 2
    grid = (alive < 3)   # True → winners bracket / superfinal
    if loser still alive (losses < 2):
        move loser to next DE match on given grid
    if winner has losses > 0:
        move winner to next DE match on given grid
    else:
        move winner to next DE match on winners (True)

state.last_m = m_idx
state.last_p = loser_slot
```

### 16.5 `sorted_results`

```
if RR:
    sort all players by (−wins, losses)
    wins = played − losses
else (SE/DE):
    (w_idx, l_idx) = get_winner_loser(state)
        → scan matches in reverse; return (winner_slot_id, loser_slot_id) of last decided
    others = players except w_idx and l_idx, sorted by (−wins, losses)
    order = [w_idx, l_idx] + others

# Group into ties
groups = []
for idx in order:
    wins, losses = players[idx].played − players[idx].losses, players[idx].losses
    if groups[-1] has same (wins, losses): append idx to last group
    else: start new group [idx]

return groups  # e.g. [[0], [3], [1, 2]]  → 1st, 2nd, tie for 3rd
```

### 16.6 Dense ranking

```
place = 0
for group in groups:
    icon = medals[place]  if place < 3  else "#" + (place+1)
    display group
    place += 1   # always +1, never += len(group)
```

Result: 3-way tie at 3rd place → next place is 4th, not 7th.

### 16.7 `_assign_rounds` — SE round labelling

```
idx = 0; r = 1; rem = n_players
while rem > 1:
    cnt = rem // 2
    for i in idx .. idx+cnt-1:
        round_map[i] = r
    idx += cnt; rem = cnt; r += 1

for each match i:
    round = round_map.get(i, r-1)
    section = "winners"
```

### 16.8 Bracket scroll position preservation

Before DOM rebuild:
```javascript
savedScrolls = [...container.querySelectorAll(".bracket-scroll")].map(el => el.scrollLeft)
```
After rebuild:
```javascript
[...container.querySelectorAll(".bracket-scroll")].forEach((el, i) => {
  if (savedScrolls[i] != null) el.scrollLeft = savedScrolls[i]
})
```
Matches by position (winners scroll first, losers second in DE).
