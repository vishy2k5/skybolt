#!/bin/sh
# Start Skybolt locally from any directory:  ./run.sh   (demo data: ./run.sh seed)
cd "$(dirname "$0")" || exit 1
if [ "$1" = "seed" ]; then exec uv run python backend/seed_demo.py; fi
exec uv run skybolt
