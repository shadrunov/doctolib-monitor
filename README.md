# Doctolib Telegram monitor

This repository performs the supplied Doctolib request directly in Python on
GitHub Actions every five minutes. It uses a Chrome-compatible TLS and HTTP
fingerprint. Its `start_date` is generated in the Berlin
timezone on every run. The first successful run records the current `next_slot` as a
dynamic baseline. A Telegram message is sent whenever a subsequent successful
response contains a strictly earlier slot.

It also sends one alert when the request changes from healthy to an HTTP error
(including HTTP 429), when the error status changes, or when an HTTP 200 response
is invalid. A recovery message is sent when valid HTTP 200 responses resume.

The workflow needs these encrypted repository secrets:

- `TELEGRAM_BOT_TOKEN`: Telegram bot token
- `TELEGRAM_CHAT_IDS`: comma-separated numeric chat IDs for every recipient

The local `request` and `token` files are intentionally ignored because they
contain credentials. GitHub schedules are best-effort and can occasionally run
later than the requested five-minute interval.

Run tests locally with:

```sh
python3 -m unittest -v
```

A separate Yandex Cloud Functions package and deployment guide are available
in [`yandex_function/`](yandex_function/README.md).
