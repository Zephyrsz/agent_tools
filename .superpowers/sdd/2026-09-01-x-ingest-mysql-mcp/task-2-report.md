# Task 2: MySQL Repository

## Delivered

- Added `PostRepository`, the persistence protocol used by ingest, crawler,
  media, and export workflows.
- Added `MySQLPostRepository`, a DB-API adapter with injectable connection
  construction, idempotent schema initialization, transactional post writes,
  crawl cursors, candidate state, and media retry state.
- Added a standard-library DB-API fake test suite for MySQL parameter style
  and repository behavior.

## Verification

`python -m unittest x_ingest.tests.test_mysql_store x_ingest.tests.test_media x_ingest.tests.test_crawler -v`

Result: 8 tests passed.

`python -m unittest discover -s x_ingest/tests -v` was also run. The MySQL,
crawler, media, config, model, and SQLite tests passed; one independently
modified gateway fixture failed because its fake matches the authentication
probe before the timeline extractor. This task did not change that fixture or
gateway.

`python -m py_compile x_ingest/mysql_store.py x_ingest/repository.py`

Result: passed.

## Commit

`3a748e5 feat(x-ingest): add transactional MySQL repository`

## Files

- `x_ingest/repository.py`
- `x_ingest/mysql_store.py`
- `x_ingest/tests/test_mysql_store.py`
