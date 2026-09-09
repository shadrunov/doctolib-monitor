# Yandex Cloud timer bridge

Yandex Cloud is used only as a reliable five-minute scheduler. The function
dispatches a `doctolib_check` event to GitHub; GitHub Actions performs the
Doctolib request, persists monitor state, evaluates alerts, and sends Telegram
messages.

## Package

Build a flat ZIP archive from the repository root:

```sh
mkdir -p dist
zip -j dist/doctolib-yandex-function.zip \
  yandex_function/index.py \
  yandex_function/requirements.txt
```

Create a function version with:

- Runtime: Python 3.12
- Entry point: `index.handler`
- Timeout: at least 30 seconds
- Memory: at least 128 MB
- `GITHUB_RELAY_REPOSITORY=shadrunov/doctolib-monitor`
- `GITHUB_RELAY_TOKEN` attached from Lockbox

The fine-grained GitHub token should be limited to this repository with only
the permission required to create repository dispatch events.

## Five-minute trigger

Create a Timer trigger with this UTC cron expression:

```text
0/5 * * * ? *
```

Attach a service account allowed to invoke the function. The GitHub workflow
handles request retries, state, and notification policy.
