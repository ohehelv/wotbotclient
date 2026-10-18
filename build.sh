#!/bin/sh
# Compiles src/mod_sandbox.py into the release folder. Requires Python 2.7 (the game runs Python 2.7).
set -e
PY=${PY27:-python2.7}
DIR=$(cd "$(dirname "$0")" && pwd)
"$PY" "$DIR/tests/mock_engine_test.py" > /dev/null
MODS="$DIR/release/eu/res_mods/2.4.1.0/scripts/client/gui/mods"
for m in mod_sandbox sandbox_native; do
  "$PY" -c "import py_compile, sys; py_compile.compile(sys.argv[1], sys.argv[2], 'scripts/client/gui/mods/' + sys.argv[3] + '.py', doraise=True)" "$DIR/src/$m.py" "$MODS/$m.pyc" "$m"
  echo "built $MODS/$m.pyc"
done
