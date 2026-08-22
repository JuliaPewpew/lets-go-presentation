import unittest
from datetime import datetime

from bot.reminders import reminder_text


class ReminderTests(unittest.TestCase):
    def test_every_reminder_kind_has_clear_copy(self):
        scheduled = datetime(2030, 8, 24, 18, 30)
        for kind in ("week", "day", "hours", "event", "followup"):
            with self.subTest(kind=kind):
                text = reminder_text(kind, "Пикник", scheduled)
                self.assertIn("Пикник", text)
                self.assertTrue(text.strip())

    def test_title_is_escaped_for_telegram_html(self):
        text = reminder_text("event", "<Пикник>", datetime(2030, 8, 24, 18, 30))
        self.assertIn("&lt;Пикник&gt;", text)
        self.assertNotIn("<Пикник>", text)


if __name__ == "__main__":
    unittest.main()
