# skybolt
A smart Home Calendar that is more than just a calendar

Python project managed with [uv](https://docs.astral.sh/uv/).

## Run locally
```
./run.sh            # starts http://127.0.0.1:8000 (installs deps on first run)
./run.sh seed       # in another terminal: load demo data (once)
uv run pytest       # tests
```
API docs: http://127.0.0.1:8000/docs
Screens can be opened directly: `/?view=month`, `/?open=weather`, `/?open=chores`, `/?open=settings`, `/?open=add`.
Weather location: set `SKYBOLT_LAT`, `SKYBOLT_LON`, `SKYBOLT_UNITS` in `.env` (see `.env.example`).
