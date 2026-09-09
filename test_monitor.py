import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from monitor import (
    Notification,
    TelegramRecipientUnavailable,
    evaluate,
    fetch_doctolib,
    send_telegram,
    send_telegram_to_all,
    telegram_chat_ids,
)


def response(slot: str) -> bytes:
    return ('{"next_slot":"' + slot + '"}').encode()


class EvaluateTests(unittest.TestCase):
    def test_multiple_telegram_chat_ids(self):
        with patch.dict("os.environ", {"TELEGRAM_CHAT_IDS": "123, 456"}):
            self.assertEqual(telegram_chat_ids(), ["123", "456"])

    def test_first_success_sets_dynamic_baseline_without_alert(self):
        state, messages = evaluate({}, 200, response("2026-10-08T16:45:00+02:00"), "")
        self.assertEqual(state["next_slot"], "2026-10-08T16:45:00+02:00")
        self.assertEqual(messages, [])

    def test_earlier_slot_alerts_normally(self):
        previous = {
            "health": "ok",
            "http_status": 200,
            "next_slot": "2026-10-08T16:45:00+02:00",
        }
        _, messages = evaluate(
            previous, 200, response("2026-09-25T09:00:00+02:00"), ""
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("Earlier", messages[0].message)
        self.assertFalse(messages[0].silent)

    def test_same_or_later_slot_does_not_alert(self):
        previous = {
            "health": "ok",
            "http_status": 200,
            "next_slot": "2026-10-08T16:45:00+02:00",
        }
        _, same = evaluate(previous, 200, response(previous["next_slot"]), "")
        _, later = evaluate(
            previous, 200, response("2026-10-09T09:00:00+02:00"), ""
        )
        self.assertEqual(same, [])
        self.assertEqual(later, [])

    def test_http_failure_alerts_on_tenth_consecutive_failure(self):
        state = {
            "health": "ok",
            "http_status": 200,
            "next_slot": "2026-10-08T16:45:00+02:00",
        }
        for attempt in range(1, 10):
            state, messages = evaluate(state, 429, b"", "")
            self.assertEqual(messages, [], f"unexpected alert on attempt {attempt}")

        state, messages = evaluate(state, 403, b"", "")
        self.assertEqual(len(messages), 1)
        self.assertIn("10 consecutive", messages[0].message)
        self.assertIn("403", messages[0].message)
        self.assertTrue(messages[0].silent)

        state, messages = evaluate(state, 503, b"", "")
        self.assertEqual(messages, [])
        self.assertEqual(state["consecutive_non_200"], 11)

    def test_success_before_threshold_resets_silently(self):
        state = {
            "health": "ok",
            "http_status": 200,
            "next_slot": "2026-10-08T16:45:00+02:00",
        }
        for _ in range(9):
            state, _ = evaluate(state, 429, b"", "")

        state, messages = evaluate(
            state, 200, response("2026-10-08T16:45:00+02:00"), ""
        )
        self.assertEqual(messages, [])
        self.assertNotIn("consecutive_non_200", state)

    def test_recovery_alerts_silently(self):
        failed = {
            "health": "error",
            "http_status": 429,
            "next_slot": "2026-10-08T16:45:00+02:00",
            "consecutive_non_200": 10,
            "failure_alerted": True,
        }
        _, messages = evaluate(
            failed, 200, response("2026-10-08T16:45:00+02:00"), ""
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("recovered", messages[0].message)
        self.assertTrue(messages[0].silent)

    def test_invalid_http_200_alert_is_silent(self):
        previous = {
            "health": "ok",
            "http_status": 200,
            "next_slot": "2026-10-08T16:45:00+02:00",
        }
        _, messages = evaluate(previous, 200, b'{"appointments": []}', "")
        self.assertEqual(len(messages), 1)
        self.assertIn("HTTP 200", messages[0].message)
        self.assertTrue(messages[0].silent)


class RequestRetryTests(unittest.TestCase):
    @patch.dict("os.environ", {"REQUEST_ATTEMPTS": "3"})
    @patch("monitor.time.sleep")
    def test_doctolib_retries_until_http_200(self, sleep):
        responses = [
            SimpleNamespace(status_code=403, content=b"", reason="Forbidden"),
            SimpleNamespace(status_code=429, content=b"", reason="Too Many Requests"),
            SimpleNamespace(status_code=200, content=b"{}", reason="OK"),
        ]
        requests = SimpleNamespace(
            get=Mock(side_effect=responses),
            errors=SimpleNamespace(RequestsError=RuntimeError),
        )

        with patch.dict("sys.modules", {"curl_cffi": SimpleNamespace(requests=requests)}):
            status, body, reason = fetch_doctolib()

        self.assertEqual((status, body, reason), (200, b"{}", "OK"))
        self.assertEqual(requests.get.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 5])

    @patch.dict("os.environ", {"REQUEST_ATTEMPTS": "3"})
    @patch("monitor.time.sleep")
    def test_telegram_retries_http_errors_and_stays_silent(self, sleep):
        failed = Mock()
        failed.status_code = 403
        failed.json.return_value = {"ok": False, "description": "Forbidden gateway"}
        failed.raise_for_status.side_effect = RuntimeError("HTTP 403")
        succeeded = Mock()
        succeeded.status_code = 200
        succeeded.raise_for_status.return_value = None
        succeeded.json.return_value = {"ok": True}
        requests = SimpleNamespace(
            post=Mock(side_effect=[failed, failed, succeeded]),
            errors=SimpleNamespace(RequestsError=RuntimeError),
        )

        with patch.dict("sys.modules", {"curl_cffi": SimpleNamespace(requests=requests)}):
            send_telegram("token", "123", "message", silent=True)

        self.assertEqual(requests.post.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 5])
        self.assertEqual(
            requests.post.call_args.kwargs["data"]["disable_notification"], "true"
        )

    @patch.dict("os.environ", {"TELEGRAM_CHAT_IDS": "blocked,active"})
    @patch("monitor.send_telegram")
    def test_blocked_chat_does_not_prevent_other_delivery(self, send):
        send.side_effect = [TelegramRecipientUnavailable("blocked"), None]

        sent = send_telegram_to_all(
            "token", Notification("message", silent=True)
        )

        self.assertEqual(sent, 1)
        self.assertEqual(send.call_count, 2)


if __name__ == "__main__":
    unittest.main()
