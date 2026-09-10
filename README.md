# Doctolib Telegram monitor

This repository performs the supplied Doctolib request in GitHub Actions. A
Yandex Cloud timer invokes a small function every five minutes; that function
dispatches the GitHub workflow. The monitor uses a Chrome-compatible TLS and
HTTP fingerprint and generates `start_date` in the Berlin timezone on every
run. The workflow currently targets slots strictly before October 5, 2026 and
records every observed `next_slot` as a dynamic baseline. A Telegram message is
sent when a qualifying slot is newly earlier than the previous observation.

Doctolib and Telegram requests are attempted up to three times. One silent
failure alert is sent after 10 consecutive scheduled checks end with a non-200
response. Invalid HTTP 200 responses and recovery after an alerted failure are
also silent. Earlier-slot alerts use a normal Telegram notification.
One user blocking the bot is logged and skipped without preventing delivery to
the other configured chats.

The workflow needs this encrypted repository secret:

- `TELEGRAM_BOT_TOKEN`: Telegram bot token

Recipient routing is configured in the workflow: chat `REDACTED_TELEGRAM_CHAT_ID` receives all
messages, while chat `REDACTED_TELEGRAM_CHAT_ID` receives only earlier-slot alerts.

The local `request` and `token` files are intentionally ignored because they
contain credentials. The workflow has no GitHub cron schedule; Yandex Cloud is
the scheduler.

Run tests locally with:

```sh
python3 -m unittest -v
```

A separate Yandex Cloud Functions package and deployment guide are available
in [`yandex_function/`](yandex_function/README.md).
