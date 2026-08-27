from __future__ import annotations

import os


def test_remote_sqlite_is_selected_when_turso_is_configured(monkeypatch) -> None:
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://gateway-org.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "test-token")

    import remote_sqlite

    connection = remote_sqlite.connect(":memory:")
    assert connection.is_remote is True
    connection.close()


def test_remote_row_supports_sqlite_style_access() -> None:
    from remote_sqlite import RemoteRow

    row = RemoteRow(("id", "status"), ("abc", "active"))

    assert row["id"] == "abc"
    assert row["status"] == "active"
    assert row[0] == "abc"
    assert row[1] == "active"
