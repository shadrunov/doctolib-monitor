import json
import unittest
from unittest.mock import patch

from yandex_function import index


class HandlerTests(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {
            "GITHUB_RELAY_TOKEN": "test-token",
            "GITHUB_RELAY_REPOSITORY": "owner/repository",
        },
        clear=False,
    )
    @patch("yandex_function.index.send_github_dispatch")
    def test_handler_dispatches_github_monitor(self, dispatch):
        response = index.handler({}, object())

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(json.loads(response["body"])["dispatched"])
        dispatch.assert_called_once_with(
            "test-token",
            "owner/repository",
            "doctolib_check",
            {"source": "yandex_timer"},
        )


if __name__ == "__main__":
    unittest.main()
