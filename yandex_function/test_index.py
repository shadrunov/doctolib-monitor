import json
import unittest
from unittest.mock import patch

from yandex_function import index


class HandlerTests(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_IDS": "123,456",
        },
        clear=False,
    )
    @patch("yandex_function.index.send_telegram")
    def test_explicit_telegram_test_notifies_every_chat(self, send):
        response = index.handler({"telegram_test": True}, object())

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["notifications_sent"], 2)
        self.assertEqual(send.call_count, 2)

    @patch.dict(
        "os.environ",
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_IDS": "123,456",
        },
        clear=False,
    )
    @patch("yandex_function.index.save_state")
    @patch("yandex_function.index.send_telegram")
    @patch("yandex_function.index.fetch_doctolib")
    @patch("yandex_function.index.load_state")
    def test_first_run_sets_baseline_without_notification(
        self, load_state, fetch, send, save
    ):
        load_state.return_value = {}
        fetch.return_value = (
            200,
            b'{"next_slot":"2026-10-08T16:45:00+02:00"}',
            "OK",
        )

        response = index.handler({}, object())

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["notifications_sent"], 0)
        send.assert_not_called()
        save.assert_called_once()

    @patch.dict(
        "os.environ",
        {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_IDS": "123,456",
        },
        clear=False,
    )
    @patch("yandex_function.index.save_state")
    @patch("yandex_function.index.send_telegram")
    @patch("yandex_function.index.fetch_doctolib")
    @patch("yandex_function.index.load_state")
    def test_earlier_slot_notifies_every_chat(
        self, load_state, fetch, send, save
    ):
        load_state.return_value = {
            "health": "ok",
            "http_status": 200,
            "next_slot": "2026-10-08T16:45:00+02:00",
        }
        fetch.return_value = (
            200,
            b'{"next_slot":"2026-09-20T09:00:00+02:00"}',
            "OK",
        )

        response = index.handler({}, object())

        self.assertEqual(json.loads(response["body"])["notifications_sent"], 2)
        self.assertEqual(send.call_count, 2)
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
