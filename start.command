#!/bin/sh
set -e
cd -- "$(dirname -- "$0")"
for candidate in python3 python; do
  if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    exec "$candidate" start.py "$@"
  fi
done
echo 'ExpObserver requires Python 3.10 or newer. Install Python, then run this launcher again.' >&2
exit 1
