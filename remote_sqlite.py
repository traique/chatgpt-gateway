from __future__ import annotations

import base64
import os
from typing import Any, Iterable, Sequence

from curl_cffi import requests as curl_requests

TURSO_DATABASE_URL_ENV = "TURSO_DATABASE_URL"
TURSO_AUTH_TOKEN_ENV = "TURSO_AUTH_TOKEN"
TURSO_PIPELINE_PATH = "/v2/pipeline"
REQUEST_TIMEOUT_SECONDS = 30.0


class RemoteRow:
    def __init__(self, columns: Sequence[str], values: Sequence[Any]) -> None:
        self._columns = tuple(columns)
        self._values = tuple(values)
        self._mapping = dict(zip(self._columns, self._values, strict=True))

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self):
        return iter(self._values)


class RemoteCursor:
    def __init__(self, columns: Sequence[str], rows: Sequence[Sequence[Any]], affected_row_count: int) -> None:
        self.description = tuple((column, None, None, None, None, None, None) for column in columns)
        self.rowcount = affected_row_count
        self._rows = tuple(RemoteRow(columns, row) for row in rows)
        self._index = 0

    def fetchone(self) -> RemoteRow | None:
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self) -> list[RemoteRow]:
        rows = list(self._rows[self._index :])
        self._index = len(self._rows)
        return rows


class RemoteConnection:
    is_remote = True

    def __init__(self, database_url: str, auth_token: str) -> None:
        self._database_url = normalize_database_url(database_url)
        self._auth_token = auth_token
        self.row_factory: object | None = None

    def execute(self, sql: str, parameters: Iterable[Any] = ()) -> RemoteCursor:
        values = tuple(parameters)
        statement: dict[str, Any] = {"sql": sql}
        if values:
            statement["args"] = [encode_argument(value) for value in values]

        response = curl_requests.post(
            f"{self._database_url}{TURSO_PIPELINE_PATH}",
            headers={
                "Authorization": f"Bearer {self._auth_token}",
                "Content-Type": "application/json",
            },
            json={
                "requests": [
                    {"type": "execute", "stmt": statement},
                    {"type": "close"},
                ]
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        result = extract_result(payload)
        columns = [str(column.get("name", "")) for column in result.get("cols", [])]
        rows = [decode_row(row) for row in result.get("rows", [])]
        affected_row_count = int(result.get("affected_row_count", 0))
        return RemoteCursor(columns, rows, affected_row_count)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


def connect(database_path: str = ":memory:") -> Any:
    database_url = os.getenv(TURSO_DATABASE_URL_ENV, "").strip()
    auth_token = os.getenv(TURSO_AUTH_TOKEN_ENV, "").strip()
    if database_url and auth_token:
        return RemoteConnection(database_url, auth_token)

    import sqlite3

    connection = sqlite3.connect(database_path)
    connection.is_remote = False
    return connection


def normalize_database_url(database_url: str) -> str:
    normalized = database_url.rstrip("/")
    if normalized.startswith("libsql://"):
        normalized = f"https://{normalized[len('libsql://'):]}"
    if normalized.startswith("https://") or normalized.startswith("http://"):
        return normalized
    raise ValueError("TURSO_DATABASE_URL must use libsql://, https://, or http://.")


def encode_argument(value: Any) -> dict[str, str]:
    if value is None:
        return {"type": "null", "value": ""}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": str(value)}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}
    return {"type": "text", "value": str(value)}


def extract_result(payload: Any) -> dict[str, Any]:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        raise RuntimeError("Turso returned an empty pipeline response.")
    first = results[0]
    if not isinstance(first, dict):
        raise RuntimeError("Turso returned an invalid pipeline response.")
    if first.get("type") == "error":
        raise RuntimeError(str(first.get("error", "Turso query failed.")))
    response = first.get("response")
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError("Turso returned an invalid query result.")
    return result


def decode_row(row: Any) -> tuple[Any, ...]:
    if not isinstance(row, list):
        return ()
    return tuple(decode_value(value) for value in row)


def decode_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    value_type = value.get("type")
    if value_type == "null":
        return None
    if value_type == "integer":
        return int(value.get("value", "0"))
    if value_type == "float":
        return float(value.get("value", "0"))
    if value_type == "blob":
        return base64.b64decode(str(value.get("base64", "")))
    return value.get("value")
