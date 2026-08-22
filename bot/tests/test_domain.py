import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from bot.domain import IdeaInput, ValidationError, future_datetime
from bot.photo_storage import PhotoStorage


class DomainTests(unittest.TestCase):
    def test_idea_input_normalizes_user_values(self):
        idea = IdeaInput.from_mapping({
            "title": "  Ночной пикник  ",
            "description": "  У озера  ",
            "difficulty": "2",
            "budget": 3,
            "duration": 4,
            "anonymous": True,
        })
        self.assertEqual(idea.title, "Ночной пикник")
        self.assertEqual(idea.description, "У озера")
        self.assertEqual((idea.difficulty, idea.budget, idea.duration), (2, 3, 4))

    def test_idea_input_rejects_invalid_rating(self):
        with self.assertRaisesRegex(ValidationError, "от 1 до 5"):
            IdeaInput.from_mapping({
                "title": "Ночной пикник",
                "difficulty": 0,
                "budget": 3,
                "duration": 4,
            })

    def test_future_datetime_is_shared_and_strict(self):
        now = datetime.now()
        self.assertGreater(future_datetime((now + timedelta(hours=1)).isoformat(), now=now), now)
        with self.assertRaisesRegex(ValidationError, "будущую дату"):
            future_datetime((now - timedelta(hours=1)).isoformat(), now=now)

    def test_photo_storage_validates_and_uses_database_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = PhotoStorage(str(Path(directory) / "app.db"))
            path = storage.save(b"image", "image/png")
            self.assertEqual(path.parent, Path(directory).resolve() / "photos")
            self.assertEqual(path.read_bytes(), b"image")
            with self.assertRaisesRegex(ValidationError, "JPG"):
                storage.save(b"image", "image/gif")


if __name__ == "__main__":
    unittest.main()
