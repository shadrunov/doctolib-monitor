"""Yandex Cloud Functions entry point for the Doctolib monitor."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from monitor import evaluate, fetch_doctolib, send_telegram, telegram_chat_ids


_driver = None
_pool = None
_schema_ready = False


def _table_name() -> str:
    table = os.environ.get("YDB_TABLE", "doctolib_monitor_state")
    if not re.fullmatch(r"[A-Za-z0-9_/-]+", table):
        raise ValueError("YDB_TABLE contains unsupported characters")
    return table


def _session_pool():
    global _driver, _pool
    if _pool is None:
        import ydb
        import ydb.iam

        _driver = ydb.Driver(
            endpoint=os.environ["YDB_ENDPOINT"],
            database=os.environ["YDB_DATABASE"],
            credentials=ydb.iam.MetadataUrlCredentials(),
        )
        _driver.wait(fail_fast=True, timeout=10)
        _pool = ydb.SessionPool(_driver, size=2)
    return _pool


def _ensure_schema() -> None:
    """Create the state table once for a new function instance."""
    global _schema_ready
    if _schema_ready:
        return

    table = _table_name()

    def operation(session):
        return session.execute_scheme(
            f"""
            CREATE TABLE IF NOT EXISTS `{table}` (
                state_key Utf8 NOT NULL,
                state_json Utf8 NOT NULL,
                PRIMARY KEY (state_key)
            );
            """
        )

    _session_pool().retry_operation_sync(operation)
    _schema_ready = True


def load_state() -> dict[str, Any]:
    _ensure_schema()
    table = _table_name()
    state_key = os.environ.get("STATE_KEY", "default")

    def operation(session):
        query = f"""
            DECLARE $state_key AS Utf8;
            SELECT state_json
            FROM `{table}`
            WHERE state_key = $state_key;
        """
        prepared = session.prepare(query)
        return session.transaction().execute(
            prepared, {"$state_key": state_key}, commit_tx=True
        )

    result_sets = _session_pool().retry_operation_sync(operation)
    rows = result_sets[0].rows
    if not rows:
        return {}
    state = json.loads(rows[0].state_json)
    if not isinstance(state, dict):
        raise ValueError("Stored monitor state must be a JSON object")
    return state


def save_state(state: dict[str, Any]) -> None:
    table = _table_name()
    state_key = os.environ.get("STATE_KEY", "default")
    state_json = json.dumps(state, sort_keys=True, separators=(",", ":"))

    def operation(session):
        query = f"""
            DECLARE $state_key AS Utf8;
            DECLARE $state_json AS Utf8;
            UPSERT INTO `{table}` (state_key, state_json)
            VALUES ($state_key, $state_json);
        """
        prepared = session.prepare(query)
        return session.transaction().execute(
            prepared,
            {"$state_key": state_key, "$state_json": state_json},
            commit_tx=True,
        )

    _session_pool().retry_operation_sync(operation)


def handler(event, context):
    """Run one monitor check. Entry point: ``index.handler``."""
    previous = load_state()
    status, body, request_error = fetch_doctolib()
    current, messages = evaluate(previous, status, body, request_error)

    if messages:
        token = os.environ["TELEGRAM_BOT_TOKEN"]
        for message in messages:
            for chat_id in telegram_chat_ids():
                send_telegram(token, chat_id, message)

    changed = current != previous
    if changed:
        # State is written only after every required Telegram message succeeds.
        save_state(current)

    result = {
        "http_status": status,
        "next_slot": current.get("next_slot"),
        "state_changed": changed,
        "notifications_sent": len(messages) * len(telegram_chat_ids()) if messages else 0,
    }
    print(json.dumps(result, sort_keys=True))
    return {"statusCode": 200, "body": json.dumps(result)}
