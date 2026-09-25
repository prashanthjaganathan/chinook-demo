#!/usr/bin/env bash
set -euo pipefail

EXPECTED=caf31d698a4a79c628215b552dfe6575e71be052ae02b8f18e763498f55f5d44
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE=$ROOT/data/Chinook_Sqlite.sql
DB=$ROOT/data/chinook.db

ACTUAL=$(shasum -a 256 "$SOURCE" | cut -d' ' -f1)
if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "Chinook source is not v1.4.5: expected $EXPECTED, got $ACTUAL" >&2
    exit 1
fi

rm -f "$DB"
sqlite3 "$DB" < "$SOURCE"
echo "Built $DB"
