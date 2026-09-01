# x_ingest

`x_ingest` archives original X posts through a dedicated Chrome session and
Chrome DevTools MCP. MySQL is the only production source of truth: post text,
chronological cursors, candidate decisions, and media state live in MySQL.
Images are stored under a local `media_root`; Markdown is an optional projection.

## Architecture

```text
Dedicated Chrome profile (signed in to X)
        -> Chrome DevTools MCP (stdio JSON-RPC)
        -> ChromeDevToolsMcpGateway (navigation/evaluation)
        -> CrawlCoordinator (candidate queue + detail policy)
        -> MySQLPostRepository (canonical facts and cursors)
        -> MediaDownloader (local images, retryable state)
```

Only Chrome owns cookies and tokens. Python never reads cookies, authorization
headers, or browser databases. Do not copy credentials into JSON, captures, or
MySQL.

## Installation

```bash
python3 -m pip install -r x_ingest/requirements.txt
export X_INGEST_DB_PASSWORD='your-password'
```

The MySQL database and user must already exist. The password environment
variable is selected by `mysql.password_env` in the JSON config.

## Chrome profile

Start a visible Chrome instance reserved for this tool, then sign in to X once:

```bash
open -na "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --remote-allow-origins='*' \
  --user-data-dir="$HOME/.local/share/x_ingest/chrome-devtools" \
  --profile-directory=Default \
  --no-first-run --no-default-browser-check
```

The default MCP command is `npx --yes chrome-devtools-mcp@0.13.0`; `x_ingest`
starts it and attaches to `http://127.0.0.1:9222`. `login` only waits for this
visible browser to become authenticated. It does not implement a Google OAuth
flow or handle credentials.

## Configuration

Start from [`config.example.json`](./config.example.json). Relative paths are
resolved relative to the config file. Watched users are edited only in JSON:

```json
{
  "mysql": {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "x_ingest",
    "database": "x_ingest",
    "password_env": "X_INGEST_DB_PASSWORD"
  },
  "media_root": "~/.local/share/x_ingest/media",
  "browser": {
    "cdp_url": "http://127.0.0.1:9222",
    "profile_dir": "~/.local/share/x_ingest/chrome-devtools"
  },
  "users": [{"handle": "AndrewYNg", "relation": "own_post", "enabled": true}]
}
```

## Commands

```bash
python3 -m x_ingest --config x_ingest/config.json init
python3 -m x_ingest --config x_ingest/config.json login --timeout 300
python3 -m x_ingest --config x_ingest/config.json crawl --handle AndrewYNg --mode full
python3 -m x_ingest --config x_ingest/config.json crawl --handle AndrewYNg
python3 -m x_ingest --config x_ingest/config.json retry-media
python3 -m x_ingest --config x_ingest/config.json query --handle AndrewYNg --order asc
python3 -m x_ingest --config x_ingest/config.json state --handle AndrewYNg
```

Every candidate is opened in its detail page. Only posts authored by the target
handle that are not replies, quotes, reposts, or videos are saved. A partial run
stores extracted facts but does not advance `(created_at, post_id)`; retries are
idempotent by numeric X post ID.

SQLite remains available only for offline fixtures and migration tooling:

```bash
python3 -m x_ingest --config x_ingest/config.example.json import \
  x_ingest/examples/andrewyng_recent3.json --handle AndrewYNg --storage sqlite
```

Optional Markdown export reads the selected repository and writes derived files:

```bash
python3 -m x_ingest --config x_ingest/config.json export \
  --handle AndrewYNg --vault "/path/to/vault"
```

## Testing

```bash
python3 -m unittest discover -s x_ingest/tests -v
python3 -m compileall -q x_ingest
```

The unit suite uses a DB-API fake for MySQL. Run live smoke tests only against a
disposable database and an explicitly started Chrome session. Never commit the
Chrome profile, media directory, private config, or database files.
