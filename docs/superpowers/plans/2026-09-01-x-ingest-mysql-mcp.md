# x_ingest MySQL + Chrome DevTools MCP Implementation Plan

## Files and seams

- `x_ingest/config.py`: JSON model for MySQL, MCP command, and browser limits.
- `x_ingest/config.example.json`: runnable configuration template.
- `x_ingest/mysql_store.py`: DB-API MySQL repository and schema.
- `x_ingest/repository.py`: small protocol consumed by services, crawler, and exporter.
- `x_ingest/mcp_client.py`: stdio MCP JSON-RPC client.
- `x_ingest/browser_gateway.py`: Chrome DevTools MCP adapter and extractor calls.
- `x_ingest/crawler.py`: resumable candidate/detail workflow migrated from the old branch without Browser Use.
- `x_ingest/media_downloader.py`: local image downloader and retry state.
- `x_ingest/cli.py`: MySQL lifecycle and MCP-backed commands.
- `x_ingest/extractors/*.js`: candidate and detail classification functions.
- `x_ingest/requirements.txt`: PyMySQL runtime dependency only.
- `x_ingest/tests/`: red-green tests for each seam plus existing offline tests.
- `x_ingest/README.md`: MySQL/MCP operations and security guidance.

## Tasks

1. Add failing config tests for MySQL credentials, MCP command, and path resolution; implement config parsing and validation.
2. Add failing repository tests; implement MySQL schema, transaction helpers, upserts, candidates, cursors, media state, query, and state methods.
3. Add failing MCP client tests for initialize, notifications, request IDs, stderr isolation, timeout, and malformed results; implement the stdio client.
4. Add failing gateway tests with a fake MCP client; implement page lifecycle, authentication probe, navigation, and extractor result decoding.
5. Add failing crawler tests against the repository fake; implement resumable original-only crawl and retryable candidate errors.
6. Add failing media tests; implement atomic image downloads and bounded retries.
7. Wire CLI commands to MySQL and MCP, remove Browser Use imports/dependencies, and preserve offline JSON import/export behavior.
8. Update extractors, examples, README, and `.gitignore`; add opt-in integration smoke instructions.
9. Run the full standard-library test suite, static compile checks, and a MySQL adapter dry-run with a DB-API fake. Review the diff for accidental Browser Use references and untracked user data.
