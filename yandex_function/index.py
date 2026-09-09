"""Dispatch-only Yandex Cloud Functions entry point for the Doctolib monitor."""

from __future__ import annotations

import json
import os
import re
import time


RETRY_DELAYS_SECONDS = (2, 5)


def dispatch_github_monitor() -> None:
    """Create the GitHub repository event, retrying transient/API failures."""
    from curl_cffi import requests

    repository = os.environ.get(
        "GITHUB_RELAY_REPOSITORY", "shadrunov/doctolib-monitor"
    )
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("GITHUB_RELAY_REPOSITORY must be owner/repository")

    attempts = int(os.environ.get("REQUEST_ATTEMPTS", "3"))
    if attempts < 1:
        raise ValueError("REQUEST_ATTEMPTS must be at least 1")
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.post(
                f"https://api.github.com/repos/{repository}/dispatches",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {os.environ['GITHUB_RELAY_TOKEN']}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={
                    "event_type": "doctolib_check",
                    "client_payload": {"source": "yandex_timer"},
                },
                impersonate="chrome",
                timeout=30,
            )
            response.raise_for_status()
            return
        except requests.errors.RequestsError as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(RETRY_DELAYS_SECONDS[min(attempt, len(RETRY_DELAYS_SECONDS) - 1)])

    assert last_error is not None
    raise last_error


def handler(event, context):
    """Trigger the GitHub Actions monitor. Entry point: ``index.handler``."""
    dispatch_github_monitor()
    result = {"dispatched": True}
    print(json.dumps(result, sort_keys=True))
    return {"statusCode": 200, "body": json.dumps(result)}
