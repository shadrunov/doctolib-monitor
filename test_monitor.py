import unittest
from unittest.mock import patch

from monitor import evaluate, telegram_chat_ids


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

    def test_earlier_slot_alerts(self):
        previous = {"health": "ok", "http_status": 200, "next_slot": "2026-10-08T16:45:00+02:00"}
        _, messages = evaluate(previous, 200, response("2026-09-25T09:00:00+02:00"), "")
        self.assertEqual(len(messages), 1)
        self.assertIn("Earlier", messages[0])

    def test_same_or_later_slot_does_not_alert(self):
        previous = {"health": "ok", "http_status": 200, "next_slot": "2026-10-08T16:45:00+02:00"}
        _, same = evaluate(previous, 200, response(previous["next_slot"]), "")
        _, later = evaluate(previous, 200, response("2026-10-09T09:00:00+02:00"), "")
        self.assertEqual(same, [])
        self.assertEqual(later, [])

    def test_http_failure_only_alerts_on_transition_or_changed_status(self):
        ok = {"health": "ok", "http_status": 200, "next_slot": "2026-10-08T16:45:00+02:00"}
        failed, first = evaluate(ok, 429, b"", "")
        _, repeated = evaluate(failed, 429, b"", "")
        _, changed = evaluate(failed, 403, b"", "")
        self.assertIn("429", first[0])
        self.assertEqual(repeated, [])
        self.assertIn("403", changed[0])

    def test_recovery_alerts(self):
        failed = {"health": "error", "http_status": 429, "next_slot": "2026-10-08T16:45:00+02:00"}
        _, messages = evaluate(failed, 200, response("2026-10-08T16:45:00+02:00"), "")
        self.assertEqual(len(messages), 1)
        self.assertIn("recovered", messages[0])


if __name__ == "__main__":
    unittest.main()
