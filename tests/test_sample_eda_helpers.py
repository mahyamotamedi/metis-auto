import json
import tempfile
import unittest
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "sample_eda"))

from eda_helpers import (  # noqa: E402
    data_dictionary,
    load_sessions,
    pair_bot_responses_with_preceding_users,
)


class LoadSessionsTests(unittest.TestCase):
    def test_rejects_non_object_session(self):
        payload = [{"category": "sample", "sessions": ["not a session"]}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "session 0.*object"):
                load_sessions(path)


class DataDictionaryTests(unittest.TestCase):
    def test_presence_and_types_come_from_supplied_records(self):
        categories = [{
            "category": "sample",
            "sessions": [{
                "session_id": "s1",
                "created_at": "2026-01-01",
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "bot", "content": "hi", "model": None},
                ],
            }],
        }]

        dictionary = data_dictionary(categories)
        model_row = dictionary.loc[dictionary.field.eq("model")].iloc[0]

        self.assertEqual(model_row.observed_type, "unknown")
        self.assertEqual(model_row.grain, "bot message")
        self.assertIn("1/2 have field; 1 null values", model_row.observed_presence_or_missingness)


class PairBotRequestsTests(unittest.TestCase):
    def test_uses_latest_preceding_user_and_keeps_unpaired_bot(self):
        messages = pd.DataFrame([
            {"session_id": "s1", "message_index": 0, "message_id": "u1", "role": "user", "model": None},
            {"session_id": "s1", "message_index": 1, "message_id": "b1", "role": "bot", "model": "model-a"},
            {"session_id": "s1", "message_index": 2, "message_id": "u2", "role": "user", "model": None},
            {"session_id": "s1", "message_index": 3, "message_id": "b2", "role": "bot", "model": "model-b"},
            {"session_id": "s2", "message_index": 0, "message_id": "b3", "role": "bot", "model": "model-c"},
        ])
        user_requests = pd.DataFrame([
            {"session_id": "s1", "message_index": 0, "message_id": "u1", "role": "user", "char_count": 5, "language": "English/Latin-script", "has_code_like_text": False, "exploratory_complexity_score": 0},
            {"session_id": "s1", "message_index": 2, "message_id": "u2", "role": "user", "char_count": 9, "language": "Persian-script", "has_code_like_text": True, "exploratory_complexity_score": 2},
        ])

        paired = pair_bot_responses_with_preceding_users(messages, user_requests)

        self.assertEqual(paired.request_message_id.tolist()[:2], ["u1", "u2"])
        self.assertTrue(pd.isna(paired.iloc[2].request_message_id))
        self.assertEqual(paired.model.tolist(), ["model-a", "model-b", "model-c"])


if __name__ == "__main__":
    unittest.main()
