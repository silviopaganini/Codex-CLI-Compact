#!/usr/bin/env python3
"""
Dual-Graph License Server
-------------------------
REQUIRE_LICENSE=false  → free mode  (all installs pass, no key needed)
REQUIRE_LICENSE=true   → paid mode  ($5 license key required)

Endpoints:
  POST /validate        — installer calls this with a key
  POST /generate        — you call this to create keys (needs ADMIN_SECRET)
  POST /gumroad-webhook — Gumroad calls this on purchase (auto-generates key)
  GET  /healthz         — health check
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# ── Config ────────────────────────────────────────────────────────────────────
REQUIRE_LICENSE = os.environ.get("REQUIRE_LICENSE", "false").lower() == "true"
ADMIN_SECRET    = os.environ.get("ADMIN_SECRET", "change-me-in-production")
GUMROAD_SECRET  = os.environ.get("GUMROAD_SECRET", "")  # optional webhook verification

# Email config (for sending keys to buyers)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USER)

# File URLs — served from Cloudflare R2 (private core files)
CORE_FILES_BASE = os.environ.get(
    "CORE_FILES_BASE",
    "https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
)

DB_PATH = Path(os.environ.get("DB_PATH", "/data/licenses.db"))
# ─────────────────────────────────────────────────────────────────────────────


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            key         TEXT PRIMARY KEY,
            email       TEXT,
            created_at  TEXT,
            activated   INTEGER DEFAULT 0,
            machine_id  TEXT
        )
    """)
    conn.commit()
    return conn


def generate_key() -> str:
    """XXXX-XXXX-XXXX-XXXX format."""
    raw = secrets.token_hex(8).upper()
    return "-".join(raw[i:i+4] for i in range(0, 16, 4))


def send_key_email(email: str, key: str) -> None:
    if not SMTP_USER or not SMTP_PASS:
        print(f"[license] SMTP not configured — key for {email}: {key}")
        return
    msg = EmailMessage()
    msg["Subject"] = "Your Dual-Graph License Key"
    msg["From"] = FROM_EMAIL
    msg["To"] = email
    msg.set_content(f"""
Hi,

Thank you for purchasing Dual-Graph!

Your license key: {key}

Installation:
  macOS/Linux:  curl -sSL https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.sh | bash
  Windows:      irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 | iex

Enter the key when prompted during install.

Docs: https://github.com/kunal12203/Codex-CLI-Compact

—Dual-Graph
""".strip())
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    print(f"[license] Key emailed to {email}")


class Handler(BaseHTTPRequestHandler):

    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path == "/healthz":
            self.send_json({"ok": True, "mode": "paid" if REQUIRE_LICENSE else "free"})
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/validate":
                self.handle_validate()
            elif path == "/generate":
                self.handle_generate()
            elif path == "/gumroad-webhook":
                self.handle_gumroad()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as e:  # noqa: BLE001
            self.send_json({"ok": False, "error": str(e)}, status=500)

    # ── POST /validate ────────────────────────────────────────────────────────
    def handle_validate(self) -> None:
        body = self.read_body()
        key        = str(body.get("key", "")).strip().upper()
        machine_id = str(body.get("machine_id", "")).strip()

        # Free mode — always pass
        if not REQUIRE_LICENSE:
            self.send_json({
                "ok": True,
                "mode": "free",
                "message": "Free mode — no key required",
                "files": self._file_urls(),
            })
            return

        # Paid mode — validate key
        if not key:
            self.send_json({"ok": False, "error": "License key required"}, status=403)
            return

        with get_db() as db:
            row = db.execute("SELECT * FROM licenses WHERE key = ?", (key,)).fetchone()

        if not row:
            self.send_json({"ok": False, "error": "Invalid license key"}, status=403)
            return

        # Lock key to machine on first activation
        if not row["activated"]:
            with get_db() as db:
                db.execute(
                    "UPDATE licenses SET activated=1, machine_id=? WHERE key=?",
                    (machine_id, key)
                )
                db.commit()
        elif machine_id and row["machine_id"] and row["machine_id"] != machine_id:
            self.send_json({"ok": False, "error": "Key already used on another machine"}, status=403)
            return

        self.send_json({
            "ok": True,
            "mode": "paid",
            "email": row["email"],
            "files": self._file_urls(),
        })

    # ── POST /generate ────────────────────────────────────────────────────────
    def handle_generate(self) -> None:
        body = self.read_body()
        if body.get("admin_secret") != ADMIN_SECRET:
            self.send_json({"ok": False, "error": "Unauthorized"}, status=401)
            return

        email = str(body.get("email", "")).strip()
        key   = generate_key()
        now   = datetime.now(timezone.utc).isoformat()

        with get_db() as db:
            db.execute(
                "INSERT INTO licenses (key, email, created_at) VALUES (?, ?, ?)",
                (key, email, now)
            )
            db.commit()

        if email:
            try:
                send_key_email(email, key)
            except Exception as e:  # noqa: BLE001
                print(f"[license] Email failed: {e}")

        self.send_json({"ok": True, "key": key, "email": email})

    # ── POST /gumroad-webhook ─────────────────────────────────────────────────
    def handle_gumroad(self) -> None:
        """Gumroad pings this on every sale. Auto-generates and emails a key."""
        body = self.read_body()
        email = str(body.get("email", "")).strip()

        if not email:
            self.send_json({"ok": False, "error": "No email in webhook"}, status=400)
            return

        key = generate_key()
        now = datetime.now(timezone.utc).isoformat()

        with get_db() as db:
            db.execute(
                "INSERT INTO licenses (key, email, created_at) VALUES (?, ?, ?)",
                (key, email, now)
            )
            db.commit()

        try:
            send_key_email(email, key)
        except Exception as e:  # noqa: BLE001
            print(f"[license] Email failed for {email}: {e}")

        self.send_json({"ok": True, "key": key})

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _file_urls(self) -> dict:
        """Return download URLs for core files (served from Cloudflare R2)."""
        base = CORE_FILES_BASE.rstrip("/")
        return {
            "mcp_graph_server":  f"{base}/mcp_graph_server.py",
            "graph_builder":     f"{base}/graph_builder.py",
            "dual_graph_launch": f"{base}/dual_graph_launch.sh",
            "dg":                f"{base}/dg.py",
        }

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[license] {self.address_string()} {fmt % args}")


def main() -> None:
    port = int(os.environ.get("PORT", "8900"))
    mode = "PAID" if REQUIRE_LICENSE else "FREE"
    print(f"[license] Starting in {mode} mode on port {port}")
    print(f"[license] DB: {DB_PATH}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
