#!/usr/bin/env python3
"""Poll a curl request and notify Telegram about earlier slots or HTTP failures."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DOCTOLIB_URL = "https://www.doctolib.de/availabilities.json"
DOCTOLIB_PARAMS = {
    "visit_motive_ids": "6206854",
    "agenda_ids": "803901",
    "practice_ids": "272026",
    "insurance_sector": "public",
    "telehealth": "false",
    "limit": "7",
}


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.replace(path)


def parse_slot(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("next_slot must include a timezone")
    return parsed


def fetch_doctolib() -> tuple[int, bytes, str]:
    """Perform the request with a Chrome-compatible TLS/HTTP fingerprint."""
    from curl_cffi import requests

    params = dict(DOCTOLIB_PARAMS)
    params["start_date"] = datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
    headers = {
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "max-age=0",
            "Priority": "u=0, i",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
    }
    cookie = os.environ.get("DOCTOLIB_COOKIE", "").strip()
    if cookie:
        headers["Cookie"] = cookie
    try:
        response = requests.get(
            DOCTOLIB_URL,
            params=params,
            headers=headers,
            impersonate="chrome",
            timeout=60,
        )
        return response.status_code, response.content, response.reason
    except requests.errors.RequestsError as exc:
        return 0, b"", str(exc)


def send_telegram(token: str, chat_id: str, message: str) -> None:
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram rejected the message: {payload}")


def telegram_chat_ids() -> list[str]:
    raw = os.environ["TELEGRAM_CHAT_IDS"]
    chat_ids = [item.strip() for item in raw.split(",") if item.strip()]
    if not chat_ids:
        raise ValueError("TELEGRAM_CHAT_IDS must contain at least one chat ID")
    return chat_ids


def evaluate(
    previous: dict[str, Any], status: int, body: bytes, curl_error: str
) -> tuple[dict[str, Any], list[str]]:
    state = dict(previous)
    messages: list[str] = []
    previous_health = previous.get("health")

    if status != 200:
        state["health"] = "error"
        state["http_status"] = status
        if previous_health != "error" or previous.get("http_status") != status:
            detail = f" ({curl_error})" if curl_error else ""
            messages.append(f"⚠️ Doctolib request failed: HTTP {status or 'unknown'}{detail}")
        return state, messages

    try:
        payload = json.loads(body)
        next_slot = payload["next_slot"]
        if not isinstance(next_slot, str) or not next_slot:
            raise ValueError("next_slot is missing or empty")
        current_dt = parse_slot(next_slot)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        state["health"] = "error"
        state["http_status"] = 200
        error_kind = f"invalid response: {exc}"
        state["error"] = error_kind
        if previous_health != "error" or previous.get("error") != error_kind:
            messages.append(f"⚠️ Doctolib returned HTTP 200 but {error_kind}")
        return state, messages

    if previous_health == "error":
        messages.append("✅ Doctolib request recovered and returns HTTP 200 again.")

    previous_slot = previous.get("next_slot")
    if isinstance(previous_slot, str):
        try:
            if current_dt < parse_slot(previous_slot):
                messages.append(
                    "🎉 Earlier Doctolib slot found!\n"
                    f"New: {next_slot}\nPrevious: {previous_slot}"
                )
        except ValueError:
            pass

    state = {"health": "ok", "http_status": 200, "next_slot": next_slot}
    return state, messages


def set_github_output(changed: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"state_changed={'true' if changed else 'false'}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    previous = load_state(args.state_file)
    status, body, curl_error = fetch_doctolib()

    current, messages = evaluate(previous, status, body, curl_error)
    changed = current != previous

    print(
        f"HTTP status: {status or 'unknown'}; "
        f"next_slot: {current.get('next_slot', 'unavailable')}"
    )
    if messages:
        if args.dry_run:
            for message in messages:
                print(f"Would notify: {message}")
        else:
            token = os.environ["TELEGRAM_BOT_TOKEN"]
            for message in messages:
                for chat_id in telegram_chat_ids():
                    send_telegram(token, chat_id, message)
    # Persist only after every required notification succeeds. If Telegram is
    # temporarily unavailable, the failed run will retry the alert next time.
    if changed:
        save_state(args.state_file, current)
    set_github_output(changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
