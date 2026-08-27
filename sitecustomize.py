from __future__ import annotations

import os
import sqlite3

if os.getenv("TURSO_DATABASE_URL", "").strip() and os.getenv("TURSO_AUTH_TOKEN", "").strip():
    from remote_sqlite import connect as remote_connect

    sqlite3.connect = remote_connect
