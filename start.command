#!/bin/zsh
set -e
cd -- "${0:A:h}"
if [[ ! -f dist/index.html ]]; then
  if [[ ! -d node_modules ]]; then
    npm ci
  fi
  npm run build
fi
exec python3 -m backend.server --port 4317
