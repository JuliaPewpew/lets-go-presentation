import unittest

from bot.main import invite_keyboard, menu, scale_keyboard


class UiTests(unittest.TestCase):
    def test_invite_button_contains_clickable_url(self):
        invite = "https://t.me/lets_go_friends_bot?start=join_abc-123_X"
        keyboard = invite_keyboard(invite)
        button = keyboard.inline_keyboard[0][0]
        self.assertEqual(button.url, invite)
        self.assertEqual(button.text, "Вступить в компанию 🚀")

    def test_rating_keyboard_has_values_one_to_five(self):
        keyboard = scale_keyboard("budget")
        buttons = keyboard.inline_keyboard[0]
        self.assertEqual([button.text for button in buttons], ["1", "2", "3", "4", "5"])
        self.assertEqual([button.callback_data for button in buttons], [f"budget:{n}" for n in range(1, 6)])

    def test_main_menu_contains_critical_actions(self):
        labels = {button.text for row in menu().keyboard for button in row}
        self.assertEqual(labels, {
            "🎲 Что делаем?",
            "➕ Добавить идею",
            "📋 Наш список",
            "🏆 Активность",
            "👥 Компания",
        })


if __name__ == "__main__":
    unittest.main()
