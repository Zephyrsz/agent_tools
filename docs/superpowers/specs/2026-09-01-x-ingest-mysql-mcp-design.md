# x_ingest MySQL + Chrome DevTools MCP Design

## Scope

The `codex/x-ingest-mysql-mcp-20260901` branch is based on
`origin/codex/x-ingest-andrewng-20260901`. Production ingestion uses a
persistent, dedicated Chrome profile attached through Chrome DevTools MCP and
stores canonical facts in MySQL. Browser Use is removed from runtime,
dependencies, configuration, and tests. Markdown export remains an optional
projection and is never part of the crawl transaction.

## Architecture

```text
Chrome Profile (X session)
        | localhost CDP :9222
chrome-devtools-mcp (managed child process)
        | MCP JSON-RPC over stdio
ChromeDevToolsMcpGateway
        |
CrawlCoordinator + page-context extractors
        |                     \
MySQLPostRepository          MediaStorage (local images/)
```

`BrowserGateway` is the seam between crawl orchestration and browser
transport. It exposes only `start`, `close`, `is_authenticated`,
`open_timeline`, `discover_candidates`, and `extract_detail`. The default
adapter starts a pinned `chrome-devtools-mcp` command, performs MCP
`initialize`, creates an isolated page, and invokes the configured
`navigate_page`/`evaluate_script` tools. Cookies and tokens are never read by
Python or written to MySQL.

`PostRepository` is the seam between domain workflows and persistence. The
MySQL adapter is the production implementation. The existing SQLite adapter
is retained only for offline compatibility tests and migration tooling; the
CLI defaults to MySQL and refuses a SQLite path for crawl commands.

## MySQL schema

Tables are `schema_meta`, `accounts`, `posts`, `account_posts`, `media`,
`post_candidates`, `crawl_runs`, and `crawl_state`. Numeric X status IDs are
the `posts.post_id` primary key (`BIGINT UNSIGNED`). A post is idempotently
upserted by ID; chronological pagination uses `(created_at, post_id)`.

`posts` stores normalized text, author data, post kind, video flag, content
hash, and canonical raw JSON. `media` stores remote URL, alt text, local
relative path, MIME/hash/size, and `pending|ready|failed` retry state. Candidate
rows are durable until detail extraction decides `saved`, `reply`, `quote`,
`repost`, `video`, `other`, or `error`. Successful crawl runs alone advance
the account cursors.

All writes for one extracted post are transactional. Schema initialization is
idempotent and guarded by a schema version. A migration command can be added
later; no destructive migration is required for the first release.

## Configuration and CLI

JSON configuration contains a `mysql` object (`host`, `port`, `user`,
`password_env`, `database`, `charset`, `connect_timeout`), `media_root`,
`browser` MCP command/URL/tool names, and the enabled `users` array. The
password is read from the named environment variable so it is not committed
to JSON. Existing path values are resolved relative to the config file.

Commands are `init`, `login`, `crawl`, `retry-media`, `import`, `query`,
`state`, and optional `export`. `crawl` performs candidate discovery on one
timeline, opens every candidate detail page, saves only configured-user
original posts without video, and retries media independently.

## Failure handling

MCP startup, protocol, navigation, authentication, and extractor failures
produce a partial/failed run without advancing cursors. Candidate detail
errors remain retryable. HTTP image failures update media state and do not
discard the post. A preflight validates the CDP URL and MCP process before
database work begins. The gateway serializes calls because a single isolated
tab is shared by a crawl.

## Testing

Unit tests cover MySQL SQL generation through a DB-API fake, configuration,
MCP JSON-RPC framing and tool-result decoding, gateway navigation/evaluation,
candidate decisions, idempotent persistence, and media retry semantics.
Existing SQLite/offline tests remain green. An integration smoke test is
opt-in and requires a running MySQL instance, Chrome on `9222`, and a pinned
MCP command; it is never run by the default test suite.
