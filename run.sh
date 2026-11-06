#!/bin/sh
# Start Skybolt locally from any directory:  ./run.sh   (add "seed" to load demo data: ./run.sh seed)
ROOT="$(cd "$(dirname "$0")" && pwd)"
if [ "$1" = "seed" ]; then exec "$ROOT/.venv/bin/python" "$ROOT/backend/seed_demo.py"; fi
cd "$ROOT/backend" && PYTHONPATH=. exec "$ROOT/.venv/bin/python" -m skybolt.main
