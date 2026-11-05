#!/bin/zsh
# Double-click to open the FrameEvolve workbench in your browser.
# Starts the server if it is not already running. Close this window to stop it.
cd "$(dirname "$0")"
PORT=${FRAMEEVOLVE_PORT:-8765}
URL="http://localhost:$PORT"

if curl -s -o /dev/null "$URL"; then
  open "$URL"
  exit 0
fi

UV=$(command -v uv || echo "$HOME/.local/bin/uv")
( for i in {1..100}; do curl -s -o /dev/null "$URL" && { open "$URL"; break; }; sleep 0.2; done ) &
exec "$UV" run python -m frameevolve serve --port "$PORT"
