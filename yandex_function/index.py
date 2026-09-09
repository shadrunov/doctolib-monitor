"""Dispatch-only Yandex Cloud Functions entry point for the Doctolib monitor."""

from __future__ import annotations

import json
import os

from monitor import send_github_dispatch


def handler(event, context):
    """Trigger the GitHub Actions monitor. Entry point: ``index.handler``."""
    send_github_dispatch(
        os.environ["GITHUB_RELAY_TOKEN"],
        os.environ.get("GITHUB_RELAY_REPOSITORY", "shadrunov/doctolib-monitor"),
        "doctolib_check",
        {"source": "yandex_timer"},
    )
    result = {"dispatched": True}
    print(json.dumps(result, sort_keys=True))
    return {"statusCode": 200, "body": json.dumps(result)}
