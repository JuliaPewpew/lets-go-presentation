import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode

from aiohttp import web

from bot.miniapp import validate_init_data


def signed_init_data(token: str, user: dict, auth_date: int | None = None) -> str:
    values = {"auth_date": str(auth_date or int(time.time())), "query_id": "test", "user": json.dumps(user, separators=(",", ":"))}
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class MiniAppAuthTests(unittest.TestCase):
    def test_valid_telegram_signature(self):
        user = {"id": 42, "first_name": "Юлия"}
        self.assertEqual(validate_init_data(signed_init_data("token", user), "token"), user)

    def test_tampered_telegram_signature_is_rejected(self):
        raw = signed_init_data("token", {"id": 42}) + "x"
        with self.assertRaises(web.HTTPUnauthorized):
            validate_init_data(raw, "token")

    def test_expired_telegram_signature_is_rejected(self):
        raw = signed_init_data("token", {"id": 42}, int(time.time()) - 90000)
        with self.assertRaises(web.HTTPUnauthorized):
            validate_init_data(raw, "token")


if __name__ == "__main__":
    unittest.main()
