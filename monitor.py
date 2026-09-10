#!/usr/bin/env python3
"""Poll a curl request and notify Telegram about earlier slots or HTTP failures."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
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
DEFAULT_FAILURE_THRESHOLD = 10
DEFAULT_REQUEST_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (2, 5)


@dataclass(frozen=True)
class Notification:
    message: str
    silent: bool = False
    slot_found: bool = False


class TelegramRecipientUnavailable(RuntimeError):
    """The destination permanently cannot receive messages from this bot."""


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
    attempts = int(os.environ.get("REQUEST_ATTEMPTS", str(DEFAULT_REQUEST_ATTEMPTS)))
    if attempts < 1:
        raise ValueError("REQUEST_ATTEMPTS must be at least 1")
    result: tuple[int, bytes, str] = (0, b"", "request was not attempted")
    for attempt in range(attempts):
        try:
            response = requests.get(
                DOCTOLIB_URL,
                params=params,
                headers=headers,
                impersonate="chrome",
                timeout=60,
            )
            result = (response.status_code, response.content, response.reason)
            if response.status_code == 200:
                return result
        except requests.errors.RequestsError as exc:
            result = (0, b"", str(exc))
        if attempt + 1 < attempts:
            time.sleep(RETRY_DELAYS_SECONDS[min(attempt, len(RETRY_DELAYS_SECONDS) - 1)])
    return result


def send_telegram(
    token: str, chat_id: str, message: str, silent: bool = False
) -> None:
    from curl_cffi import requests

    attempts = int(os.environ.get("REQUEST_ATTEMPTS", str(DEFAULT_REQUEST_ATTEMPTS)))
    if attempts < 1:
        raise ValueError("REQUEST_ATTEMPTS must be at least 1")
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": message,
                    "disable_notification": "true" if silent else "false",
                },
                impersonate="chrome",
                timeout=30,
            )
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            description = str(payload.get("description", ""))
            if response.status_code == 403 and "blocked by the user" in description:
                raise TelegramRecipientUnavailable(description)
            response.raise_for_status()
            if not payload.get("ok"):
                raise RuntimeError(f"Telegram rejected the message: {payload}")
            return
        except TelegramRecipientUnavailable:
            raise
        except (requests.errors.RequestsError, RuntimeError) as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(RETRY_DELAYS_SECONDS[min(attempt, len(RETRY_DELAYS_SECONDS) - 1)])
    assert last_error is not None
    raise last_error


def send_telegram_to_all(token: str, notification: Notification) -> int:
    """Deliver to every reachable chat without one blocked user stopping others."""
    sent = 0
    for chat_id in telegram_chat_ids(notification):
        try:
            send_telegram(token, chat_id, notification.message, notification.silent)
            sent += 1
        except TelegramRecipientUnavailable as exc:
            print(f"Skipping unavailable Telegram chat {chat_id}: {exc}")
    return sent


def telegram_chat_ids(notification: Optional[Notification] = None) -> list[str]:
    variable = (
        "TELEGRAM_SLOT_CHAT_IDS"
        if notification is not None and notification.slot_found
        else "TELEGRAM_ALERT_CHAT_IDS"
    )
    raw = os.environ.get(variable) or os.environ["TELEGRAM_CHAT_IDS"]
    chat_ids = [item.strip() for item in raw.split(",") if item.strip()]
    if not chat_ids:
        raise ValueError("TELEGRAM_CHAT_IDS must contain at least one chat ID")
    return chat_ids


def failure_threshold() -> int:
    raw = os.environ.get("FAILURE_THRESHOLD", str(DEFAULT_FAILURE_THRESHOLD))
    try:
        threshold = int(raw)
    except ValueError as exc:
        raise ValueError("FAILURE_THRESHOLD must be an integer") from exc
    if threshold < 1:
        raise ValueError("FAILURE_THRESHOLD must be at least 1")
    return threshold


def slot_cutoff() -> Optional[datetime]:
    raw = os.environ.get("SLOT_CUTOFF")
    return parse_slot(raw) if raw else None


def evaluate(
    previous: dict[str, Any],
    status: int,
    body: bytes,
    curl_error: str,
    non_200_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    cutoff: Optional[datetime] = None,
) -> tuple[dict[str, Any], list[Notification]]:
    if non_200_threshold < 1:
        raise ValueError("non_200_threshold must be at least 1")
    state = dict(previous)
    messages: list[Notification] = []
    previous_health = previous.get("health")

    if status != 200:
        previous_count = previous.get("consecutive_non_200", 0)
        if not isinstance(previous_count, int) or previous_count < 0:
            previous_count = 0
        failure_count = previous_count + 1
        state["health"] = "error"
        state["http_status"] = status
        state["consecutive_non_200"] = failure_count
        state["failure_alerted"] = bool(previous.get("failure_alerted"))
        state.pop("error", None)
        if failure_count >= non_200_threshold and not state["failure_alerted"]:
            detail = f" ({curl_error})" if curl_error else ""
            messages.append(
                Notification(
                    "⚠️ Doctolib request failed "
                    f"{failure_count} consecutive times: HTTP {status or 'unknown'}{detail}",
                    silent=True,
                )
            )
            state["failure_alerted"] = True
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
        state["consecutive_non_200"] = 0
        state["failure_alerted"] = False
        error_kind = f"invalid response: {exc}"
        state["error"] = error_kind
        if previous_health != "error" or previous.get("error") != error_kind:
            messages.append(
                Notification(
                    f"⚠️ Doctolib returned HTTP 200 but {error_kind}", silent=True
                )
            )
        return state, messages

    if previous_health == "error" and (
        previous.get("failure_alerted") or previous.get("http_status") == 200
    ):
        messages.append(
            Notification(
                "✅ Doctolib request recovered and returns HTTP 200 again.",
                silent=True,
            )
        )

    previous_slot = previous.get("next_slot")
    previous_dt = None
    if isinstance(previous_slot, str):
        try:
            previous_dt = parse_slot(previous_slot)
        except ValueError:
            pass

    is_new_earlier_slot = previous_dt is None or current_dt < previous_dt
    is_before_cutoff = cutoff is None or current_dt < cutoff
    has_comparison_target = previous_dt is not None or cutoff is not None
    if is_new_earlier_slot and is_before_cutoff and has_comparison_target:
        comparison = previous_slot if previous_dt is not None else cutoff.isoformat()
        messages.append(
            Notification(
                "🎉 Earlier Doctolib slot found!\n"
                f"New: {next_slot}\nPrevious/cutoff: {comparison}",
                slot_found=True,
            )
        )

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

    current, messages = evaluate(
        previous, status, body, curl_error, failure_threshold(), slot_cutoff()
    )
    changed = current != previous

    print(
        f"HTTP status: {status or 'unknown'}; "
        f"next_slot: {current.get('next_slot', 'unavailable')}"
    )
    if messages:
        if args.dry_run:
            for message in messages:
                print(f"Would notify: {message.message}")
        else:
            token = os.environ["TELEGRAM_BOT_TOKEN"]
            for message in messages:
                send_telegram_to_all(token, message)
    # Persist only after every required notification succeeds. If Telegram is
    # temporarily unavailable, the failed run will retry the alert next time.
    if changed:
        save_state(args.state_file, current)
    set_github_output(changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
