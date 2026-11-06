# skybolt
A smart Home Calendar that is more than just a calendar

## Run locally
```
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && PYTHONPATH=. ../.venv/bin/python -m skybolt.main   # http://127.0.0.1:8000
PYTHONPATH=. ../.venv/bin/pytest                                  # tests
```
API docs: http://127.0.0.1:8000/docs

Demo data (while the server runs): `cd backend && ../.venv/bin/python seed_demo.py`
Screens can be opened directly: `/?view=month`, `/?open=weather`, `/?open=chores`, `/?open=add`.
Weather location: set `SKYBOLT_LAT`, `SKYBOLT_LON`, `SKYBOLT_UNITS` in `.env` (see `.env.example`).
