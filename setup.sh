#!/bin/bash
# Claude Context Window Tracker — Setup & Auto-Launch Installer
# Run: chmod +x setup.sh && ./setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.paully.claude-context-tracker"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
SCRIPT_PATH="$SCRIPT_DIR/context_tracker.py"

echo "🔧 Setting up Claude Context Window Tracker..."
echo ""

# ── Check Python 3 ──────────────────────────────────────────────────────
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Install via: brew install python3"
    exit 1
fi
PYTHON3_PATH="$(which python3)"
echo "✅ Python 3: $PYTHON3_PATH"

# ── Install dependencies ────────────────────────────────────────────────
echo "📦 Installing dependencies..."
pip3 install rumps pynput --quiet
echo "✅ rumps + pynput installed"

# ── Install LaunchAgent (auto-start on login) ───────────────────────────
echo ""
echo "🚀 Installing LaunchAgent for auto-start on login..."

# Unload existing if present
if launchctl list | grep -q "$PLIST_NAME" 2>/dev/null; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# Patch plist with actual paths
mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__PYTHON3_PATH__|$PYTHON3_PATH|g" \
    -e "s|__SCRIPT_PATH__|$SCRIPT_PATH|g" \
    "$PLIST_SRC" > "$PLIST_DEST"

# Load it
launchctl load "$PLIST_DEST"
echo "✅ LaunchAgent installed: $PLIST_DEST"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ Setup complete! The tracker is now running."
echo "════════════════════════════════════════════════════════"
echo ""
echo "  Menu bar:  Look for the 🟢 0% indicator"
echo "  Hotkey:    Ctrl+Shift+C  → count tokens from clipboard"
echo "  Workflow:  Cmd+A → Cmd+C in Claude, then Ctrl+Shift+C"
echo ""
echo "  It will auto-start on every login."
echo ""
echo "  To stop:   launchctl unload $PLIST_DEST"
echo "  To remove: rm $PLIST_DEST"
echo "  Logs:      /tmp/claude-context-tracker.log"
echo ""
echo "  ⚠️  macOS will ask for Accessibility permission for"
echo "     the hotkey to work. Grant it when prompted."
echo "════════════════════════════════════════════════════════"
