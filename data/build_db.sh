#!/usr/bin/env bash
set -euo pipefail

EXPECTED=caf31d698a4a79c628215b552dfe6575e71be052ae02b8f18e763498f55f5d44
DIR=$(cd "$(dirname "$0")" && pwd)

ACTUAL=$(shasum -a 256 "$DIR/Chinook_Sqlite.sql" | cut -d' ' -f1)
if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "Chinook source is not v1.4.5: got $ACTUAL" >&2
    exit 1
fi

rm -f "$DIR/chinook.db"
sqlite3 "$DIR/chinook.db" < "$DIR/Chinook_Sqlite.sql"
echo "Built $DIR/chinook.db"
