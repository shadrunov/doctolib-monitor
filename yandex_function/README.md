# Yandex Cloud Functions version

This version runs the same monitor inside Yandex Cloud Functions. It uses a
Serverless YDB table for durable state because function instances are
stateless and may be replaced between timer invocations.

## Package

Build a flat ZIP archive from the repository root:

```sh
mkdir -p dist
zip -j dist/doctolib-yandex-function.zip \
  yandex_function/index.py \
  monitor.py \
  yandex_function/requirements.txt
```

Create a function version with:

- Runtime: Python 3.12
- Entry point: `index.handler`
- Timeout: at least 60 seconds
- Memory: at least 256 MB
- An attached service account that can read and write the selected YDB database

## Persistent state

Create a Serverless YDB database. The function creates the state table
idempotently on its first invocation; `schema.sql` is also available for
manual initialization. Set these function environment variables from the
database endpoint:

- `YDB_ENDPOINT`, for example `grpcs://ydb.serverless.yandexcloud.net:2135`
- `YDB_DATABASE`, the database path beginning with `/ru-central1/...`
- `YDB_TABLE=doctolib_monitor_state`
- `STATE_KEY=default` (optional)

The function uses the attached service account through Yandex's metadata
credentials; no static YDB access key is required.

## Telegram variables

Set:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_IDS`, a comma-separated list of numeric chat IDs

Store both values in Yandex Lockbox and attach them to the function as secret
environment variables. Grant `lockbox.payloadViewer` only on that secret to
the function's service account.

## Five-minute trigger

Create a Timer trigger for the function with this UTC cron expression:

```text
0/5 * * * ? *
```

Attach a service account allowed to invoke the function. Configure retries if
desired; Telegram or YDB failures are raised so the timer can retry them.

The first successful invocation establishes the dynamic baseline. Later
invocations notify every configured Telegram chat about an earlier slot, an
HTTP failure transition, or recovery.
