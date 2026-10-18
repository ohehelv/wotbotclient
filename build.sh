#!/bin/sh
# Compiles src/mod_sandbox.py into the release folder. Requires Python 2.7 (the game runs Python 2.7).
set -e
PY=${PY27:-python2.7}
DIR=$(cd "$(dirname "$0")" && pwd)
OUT="$DIR/release/eu/res_mods/2.4.1.0/scripts/client/gui/mods/mod_sandbox.pyc"
"$PY" "$DIR/tests/mock_engine_test.py" > /dev/null
"$PY" -c "import py_compile, sys; py_compile.compile(sys.argv[1], sys.argv[2], 'scripts/client/gui/mods/mod_sandbox.py', doraise=True)" "$DIR/src/mod_sandbox.py" "$OUT"
echo "built $OUT"
