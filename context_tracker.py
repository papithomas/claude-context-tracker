#!/usr/bin/env python3
"""
Claude Context Window Tracker — macOS Menu Bar Widget
Estimates token usage in claude.ai conversations via clipboard analysis.

Usage:
  1. In your Claude conversation, Cmd+A → Cmd+C to copy the full chat
  2. Click the menu bar icon → "Count from Clipboard"
  3. See your estimated context usage at a glance

Token estimation uses ~3.5 chars/token (conservative for English + code mix).
Claude's context window: 200K tokens (claude.ai web interface).
Warning thresholds calibrated to context rot research (Chroma, Stanford, Manus).
"""

import rumps
import subprocess
import json
import os
import time
import threading
from datetime import datetime
from pynput import keyboard

# ── Config ──────────────────────────────────────────────────────────────────
MAX_TOKENS = 200_000
CHARS_PER_TOKEN = 3.5  # conservative estimate for mixed English + code
# Thresholds based on context rot research (Chroma 2025, Stanford "Lost in the
# Middle", AgentPatterns RULER study, Manus context engineering). Degradation is
# measurable at every length increment. These tiers reflect practical quality zones:
#   🟢  0-35%  (0-70K)   — High quality, full recall
#   🟠 35-60%  (70-120K) — Mild degradation; middle-content recall weakening
#   🟡 60-80%  (120-160K)— Significant rot; reasoning & code accuracy drop
#   🔴 80%+    (160K+)   — Severe; start a new conversation
WARNING_THRESHOLDS = {
    0.80: "🔴",
    0.60: "🟡",
    0.35: "🟠",
    0.00: "🟢",
}
STATE_FILE = os.path.expanduser("~/.claude_context_tracker.json")
BAR_LENGTH = 8
# Global hotkey: Ctrl+Shift+C triggers "Replace from Clipboard"
HOTKEY_COMBO = {keyboard.Key.ctrl, keyboard.Key.shift}
HOTKEY_CHAR = "c"

# ── Helpers ─────────────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Estimate token count from text. ~3.5 chars/token for mixed content."""
    if not text:
        return 0
    return int(len(text) / CHARS_PER_TOKEN)


def get_clipboard() -> str:
    """Read macOS clipboard via pbpaste."""
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
        return result.stdout
    except Exception:
        return ""


def make_bar(fraction: float) -> str:
    """Build a compact progress bar string."""
    filled = int(fraction * BAR_LENGTH)
    return "▰" * filled + "▱" * (BAR_LENGTH - filled)


def get_status_emoji(fraction: float) -> str:
    """Get color emoji based on usage threshold."""
    for threshold, emoji in sorted(WARNING_THRESHOLDS.items(), reverse=True):
        if fraction >= threshold:
            return emoji
    return "🟢"


def format_tokens(n: int) -> str:
    """Format token count as human-readable string."""
    if n >= 1000:
        return f"{n / 1000:.1f}K"
    return str(n)


# ── App ─────────────────────────────────────────────────────────────────────

class ContextTracker(rumps.App):
    def __init__(self):
        super().__init__("CW", quit_button=None)
        self.conversations = {}  # name -> {"tokens": int, "updated": str}
        self.active_convo = "Chat 1"
        self.load_state()
        self._rebuild_menu()
        self._update_title()
        self._start_hotkey_listener()

    def _start_hotkey_listener(self):
        """Start a background thread listening for Ctrl+Shift+C global hotkey."""
        self._pressed_keys = set()

        def on_press(key):
            if key in HOTKEY_COMBO:
                self._pressed_keys.add(key)
            try:
                if hasattr(key, "char") and key.char == HOTKEY_CHAR and HOTKEY_COMBO.issubset(self._pressed_keys):
                    # Fire on main thread via rumps timer trick
                    self._replace_clipboard(None)
            except AttributeError:
                pass

        def on_release(key):
            self._pressed_keys.discard(key)

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()

    # ── State persistence ───────────────────────────────────────────────

    def load_state(self):
        """Load saved state from disk."""
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    data = json.load(f)
                self.conversations = data.get("conversations", {})
                self.active_convo = data.get("active", "Chat 1")
        except Exception:
            pass
        if not self.conversations:
            self.conversations = {"Chat 1": {"tokens": 0, "updated": ""}}

    def save_state(self):
        """Persist state to disk."""
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({
                    "conversations": self.conversations,
                    "active": self.active_convo,
                }, f)
        except Exception:
            pass

    # ── Display ─────────────────────────────────────────────────────────

    def _get_tokens(self) -> int:
        return self.conversations.get(self.active_convo, {}).get("tokens", 0)

    def _update_title(self):
        tokens = self._get_tokens()
        frac = min(tokens / MAX_TOKENS, 1.0)
        pct = frac * 100
        emoji = get_status_emoji(frac)
        bar = make_bar(frac)
        self.title = f"{emoji} {pct:.0f}% {bar}"

    def _rebuild_menu(self):
        """Rebuild the dropdown menu."""
        self.menu.clear()
        tokens = self._get_tokens()
        frac = min(tokens / MAX_TOKENS, 1.0)

        # Header info
        self.menu.add(rumps.MenuItem(
            f"Active: {self.active_convo}",
            callback=None
        ))
        self.menu.add(rumps.MenuItem(
            f"{format_tokens(tokens)} / {format_tokens(MAX_TOKENS)} tokens ({frac * 100:.1f}%)",
            callback=None
        ))
        self.menu.add(rumps.separator)

        # Actions
        self.menu.add(rumps.MenuItem("📋 Count from Clipboard", callback=self._count_clipboard))
        self.menu.add(rumps.MenuItem("🔄 Replace from Clipboard (⌃⇧C)", callback=self._replace_clipboard))
        self.menu.add(rumps.MenuItem("➕ Add Quick Estimate (+2K)", callback=self._quick_add))
        self.menu.add(rumps.separator)

        # Conversation management
        convo_submenu = rumps.MenuItem("💬 Conversations")
        for name in sorted(self.conversations.keys()):
            prefix = "● " if name == self.active_convo else "○ "
            item = rumps.MenuItem(f"{prefix}{name}", callback=self._switch_convo)
            convo_submenu.add(item)
        convo_submenu.add(rumps.separator)
        convo_submenu.add(rumps.MenuItem("New Conversation…", callback=self._new_convo))
        self.menu.add(convo_submenu)

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("🗑️ Reset Active Chat", callback=self._reset_active))
        self.menu.add(rumps.MenuItem("🗑️ Reset All", callback=self._reset_all))
        self.menu.add(rumps.separator)

        # Settings info
        settings_sub = rumps.MenuItem("⚙️ Settings")
        settings_sub.add(rumps.MenuItem(
            f"Max tokens: {format_tokens(MAX_TOKENS)}",
            callback=None
        ))
        settings_sub.add(rumps.MenuItem(
            f"Ratio: ~{CHARS_PER_TOKEN} chars/token",
            callback=None
        ))
        self.menu.add(settings_sub)
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Quit", callback=rumps.quit_application))

    def _refresh(self):
        self._update_title()
        self._rebuild_menu()
        self.save_state()

    # ── Actions ─────────────────────────────────────────────────────────

    def _count_clipboard(self, _):
        """Add clipboard token estimate to current count."""
        text = get_clipboard()
        if not text.strip():
            rumps.notification(
                "Context Tracker",
                "Clipboard empty",
                "Copy your Claude conversation first (Cmd+A → Cmd+C)",
            )
            return
        new_tokens = estimate_tokens(text)
        self.conversations[self.active_convo]["tokens"] += new_tokens
        self.conversations[self.active_convo]["updated"] = datetime.now().isoformat()
        self._refresh()
        frac = self._get_tokens() / MAX_TOKENS * 100
        rumps.notification(
            "Context Tracker",
            f"+{format_tokens(new_tokens)} tokens added",
            f"Total: {format_tokens(self._get_tokens())} ({frac:.0f}%)",
        )

    def _replace_clipboard(self, _):
        """Replace current count with clipboard estimate (for full-conversation paste)."""
        text = get_clipboard()
        if not text.strip():
            rumps.notification(
                "Context Tracker",
                "Clipboard empty",
                "Copy your Claude conversation first (Cmd+A → Cmd+C)",
            )
            return
        new_tokens = estimate_tokens(text)
        self.conversations[self.active_convo]["tokens"] = new_tokens
        self.conversations[self.active_convo]["updated"] = datetime.now().isoformat()
        self._refresh()
        frac = self._get_tokens() / MAX_TOKENS * 100
        rumps.notification(
            "Context Tracker",
            f"Set to {format_tokens(new_tokens)} tokens",
            f"Usage: {frac:.0f}%",
        )

    def _quick_add(self, _):
        """Add a rough 2K token estimate (avg message exchange)."""
        self.conversations[self.active_convo]["tokens"] += 2000
        self.conversations[self.active_convo]["updated"] = datetime.now().isoformat()
        self._refresh()

    def _switch_convo(self, sender):
        """Switch active conversation."""
        name = sender.title.lstrip("● ○ ").strip()
        if name in self.conversations:
            self.active_convo = name
            self._refresh()

    def _new_convo(self, _):
        """Create a new conversation tracker."""
        window = rumps.Window(
            message="Enter a name for this conversation:",
            title="New Conversation",
            default_text=f"Chat {len(self.conversations) + 1}",
            ok="Create",
            cancel="Cancel",
        )
        response = window.run()
        if response.clicked and response.text.strip():
            name = response.text.strip()
            self.conversations[name] = {"tokens": 0, "updated": ""}
            self.active_convo = name
            self._refresh()

    def _reset_active(self, _):
        """Reset the active conversation's token count."""
        self.conversations[self.active_convo] = {"tokens": 0, "updated": ""}
        self._refresh()
        rumps.notification("Context Tracker", "Reset", f"{self.active_convo} cleared")

    def _reset_all(self, _):
        """Reset all conversations."""
        self.conversations = {"Chat 1": {"tokens": 0, "updated": ""}}
        self.active_convo = "Chat 1"
        self._refresh()
        rumps.notification("Context Tracker", "Reset All", "All conversations cleared")


# ── Entry ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ContextTracker().run()
