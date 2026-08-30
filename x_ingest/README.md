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
