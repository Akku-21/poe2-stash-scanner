#!/usr/bin/env bash
# Start the Waystone brain pricing service.
# Usage: ./start_brain.sh [waystone-brain-dir]
#
# The brain listens on a Unix socket and prices PoE2 items via the
# trade API. Keep this running while using the stash scanner.

BRAIN_DIR="${1:-/home/akku/source/waystone/brain}"
SOCKET="${BRAIN_SOCKET:-/tmp/poe2-brain.sock}"
LEAGUE="${POE2_LEAGUE:-Standard}"

if [[ ! -f "$BRAIN_DIR/package.json" ]]; then
    echo "[ERROR] Brain directory not found: $BRAIN_DIR"
    echo "  Clone it: git clone https://github.com/kriskruse/waystone /home/akku/source/waystone"
    echo "  Then: cd /home/akku/source/waystone/brain && npm install"
    exit 1
fi

if [[ ! -d "$BRAIN_DIR/node_modules" ]]; then
    echo "[INFO] Installing brain dependencies..."
    cd "$BRAIN_DIR" && npm install
fi

echo "[brain] Starting on socket: $SOCKET (league: $LEAGUE)"
cd "$BRAIN_DIR" && BRAIN_SOCKET="$SOCKET" POE2_LEAGUE="$LEAGUE" npx tsx src/server.ts
