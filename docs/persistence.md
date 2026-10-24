# Persistence: database, files, migrations, backup

## Running the app

One command, from the repository root with `.venv` active:

```
python -m scanger.dev            # then open http://127.0.0.1:7861
python -m scanger.dev --no-db    # skip Docker/migrations if the database is already up
```

It starts the database (`docker compose up -d --wait db`), applies migrations
(`alembic upgrade head`), then runs the three processes below with
`[visualmatch]`, `[scanger-api]` and `[frontend]` prefixed logs in one
terminal. Ctrl-C stops all three; if any of them exits, the rest are stopped
too. The database container keeps running (data is kept). It refuses to start
if one of the ports (8001, 8010, 7861) is already in use, so stop any
manually started copies first. Ports follow `VISUALMATCH_API_URL` and
`SCANGER_API_URL`; the frontend is fixed at 7861.

### Running the processes separately

The same three processes, each in its own terminal (database up first), for
example when you want `--reload` on one of them:

```
# 1. VisualMatch API (unchanged upstream; loads the model on the first search)
cd upstream/visualmatch && uvicorn api.app:app --host 127.0.0.1 --port 8001

# 2. Scanger API (sessions, uploads, history; forwards searches to 1.)
uvicorn scanger.api:app --host 127.0.0.1 --port 8010

# 3. Scanger frontend, then open http://127.0.0.1:7861
python -m scanger.frontend
```

The browser only talks to the frontend; the frontend only talks to the Scanger
API; only the Scanger API talks to VisualMatch (`scanger/retrieval.py`). If
VisualMatch is down, the search is saved as a failed run with the reason.
Searches still running when the Scanger API stops are marked `interrupted` on
its next start and can be run again. Run a single Scanger API process (no
`--workers`); `--reload` is fine for development.

Run all commands from the repository root with `.venv` active. Settings live in
`.env` (see `.env.example`). Scanger's database is its own Compose project
(`scanger`), container (`scanger-db`) and volume (`scanger_scanger_pgdata`), on
host port 5433. It does not use or affect any other project's containers.

## Start / stop

```
docker compose up -d db     # start; it also comes back when Docker Desktop restarts
docker compose ps           # STATUS should say "healthy"
docker compose stop db      # stop; data is kept
docker compose logs db      # troubleshooting
```

`docker compose down` is also safe (the volume is kept). Do not add `-v` and do
not run `docker volume rm`: that deletes every session.

## Migrations

```
alembic upgrade head                              # apply (idempotent)
alembic current                                   # show applied revision
alembic revision --autogenerate -m "what changed" # after editing scanger/models.py
```

Always read a generated migration before applying it.

## Files

Uploaded images are copied to `DATA_ROOT/uploads/<asset-id>.<ext>` (default
`./user-data`, gitignored). The database stores only the relative key, so
`DATA_ROOT` can move. Images are served by asset ID from the Scanger API
(`GET /assets/{id}`). Uploading identical bytes again reuses the existing asset.

Saved results store the dataset `item_id` (stable) plus a locator with the
dataset position; their images are served from the locally cached Hugging Face
dataset via `GET /results/{run_id}/{rank}/image`. If the position no longer
holds the same `item_id`, the item is looked up by `item_id`.

`find_orphan_files` (in `scanger/assets.py`) lists files with no database row,
for example after a crash mid-upload. It only reports; delete by hand if wanted.

## Backup (database + files are one set)

```
mkdir -p ~/Scanger-backups
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > ~/Scanger-backups/scanger-$(date +%F).sql
tar -czf ~/Scanger-backups/user-data-$(date +%F).tar.gz user-data
```

Restore (into an empty database, with the same-date pair of files):

```
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  < ~/Scanger-backups/scanger-YYYY-MM-DD.sql
tar -xzf ~/Scanger-backups/user-data-YYYY-MM-DD.tar.gz   # or extract anywhere and set DATA_ROOT
```

The restore procedure is documented but not yet tested end to end (M01
acceptance check 8).

## Tests

```
python -m pytest
```

Database tests create and drop a throwaway database `scanger_test` on the
running Compose server, built by the real Alembic migrations. They never touch
the `scanger` database or `user-data/`.
