# x_ingest

`x_ingest` archives rendered X/Twitter timeline posts into SQLite, supports
incremental cursors and queries, and exports stable Markdown files to Obsidian.
Browser authentication remains in a dedicated Chrome profile; cookies and
credentials are never stored in this project or in SQLite.

## Layout

```text
x_ingest/
├── models.py             canonical Post and MediaItem models
├── importers.py          extractor JSON reader
├── store.py              SQLite schema and repository
├── service.py            begin/upsert/finish ingestion workflow
├── obsidian.py           deterministic Markdown export
├── analysis.py           optional LLM document-quality analysis
├── config.py             JSON configuration reader
├── cli.py                unified command line interface
├── extractors/           JavaScript run inside an authenticated X page
├── examples/             captured AndrewYNg example data
└── tests/                standard-library unit tests
```

SQLite is the source of truth. Obsidian files are derived output and may be
regenerated. Keep the active SQLite database outside iCloud/Obsidian because
WAL mode also creates `-wal` and `-shm` files.

## Configuration

Copy `config.example.json` to a private location and update the database and
vault paths. A user handle is a configuration value, not a hard-coded author.

```json
{
  "database": "~/.local/share/x_ingest/posts.sqlite3",
  "obsidian": {"vault": "/path/to/vault", "folder": "X Clips"},
  "users": [{"handle": "AndrewYNg", "relation": "own_post", "enabled": true}]
}
```

## Workflow

### Chrome DevTools MCP authentication

Use a dedicated persistent Chrome profile and sign in to X once in that
profile. Chrome keeps the encrypted session cookies in the profile and adds
them to X requests automatically, including HttpOnly cookies. The MCP client
should attach to Chrome; it should not export Cookie or Authorization header
values into source files, shell history, captured JSON, or SQLite.

```bash
open -na "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --remote-allow-origins='*' \
  --user-data-dir="$HOME/.local/share/x_ingest/chrome-devtools" \
  --profile-directory=Default \
  --no-first-run \
  --no-default-browser-check
```

Configure Chrome DevTools MCP to attach to the same browser:

```bash
npx chrome-devtools-mcp@latest --browserUrl=http://127.0.0.1:9222
```

The X session can expire or be revoked. When that happens, open X in this
dedicated profile and sign in again. Do not copy cookie values into config.

For a historical backfill, search one bounded year at a time with the Live
tab selected:

```text
from:AndrewYNg since:2022-01-01 until:2023-01-01 -filter:replies
```

Run `extractors/timeline.js` in the page through DevTools MCP and save its JSON
result under a private capture directory. Import only after checking that the
page loaded posts and did not return HTTP 429. A zero-row result collected
while X endpoints are rate limited is invalid, not proof that the year is
empty. On 429, navigate the X tab to `about:blank`, wait 10-20 minutes, and
retry one window. Avoid concurrent X tabs and rapid reloads.

Captured batches remain partial until the intended time boundary and X
Articles have been independently reconciled. Overlap at yearly boundaries is
expected; SQLite deduplicates by post ID. If scrolling stops before the
`since` boundary, or a high-volume result appears capped, split that period
into quarterly or monthly windows. An idle scrollbar is not proof that the
query window is complete.

Initialize and import a captured batch:

```bash
python3 -m x_ingest --config x_ingest/config.example.json init
python3 -m x_ingest --config x_ingest/config.example.json import \
  x_ingest/examples/andrewyng_recent3.json --handle AndrewYNg --mode full
```

Query and inspect the successful incremental cursor:

```bash
python3 -m x_ingest --config x_ingest/config.example.json query \
  --handle AndrewYNg --after 2026-01-01T00:00:00Z \
  --after-id 2000000000000000000 --order asc
python3 -m x_ingest --config x_ingest/config.example.json state --handle AndrewYNg
```

Export to Obsidian:

```bash
python3 -m x_ingest --config x_ingest/config.example.json export --handle AndrewYNg
```

Analyze exported notes:

```bash
python3 -m x_ingest analyze --author-dir "/path/to/vault/X Clips/Andrew Ng"
```

## Incremental contract

The stable cursor is `(created_at, post_id)`. A crawler should persist batches
frequently and mark the run successful only after reaching its intended time
boundary. Partial runs still store discovered posts, but do not advance
`crawl_state`. `post_id` is the database primary key, so retries are safe.

The scripts in `extractors/` are page-context functions. `timeline.js` accepts
`handle`, `limit`, `maxScrolls`, `maxIdleScrolls`, `waitMs`, `skipPinned`,
`skipVideos`, and `sortOrder`. They intentionally do not read browser cookies.
Timeline output defaults to `partial`; set `markComplete` only after an
orchestrator has verified the intended newest/oldest boundary.
