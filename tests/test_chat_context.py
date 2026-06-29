import unittest
from collections import Counter
from datetime import timedelta
from unittest.mock import patch

import pandas as pd

from src.services.chat_context import (
    _build_messages_by_ist_timestamp,
    context_for,
)


class ChatContextTests(unittest.TestCase):
    def setUp(self):
        rows = []
        for day in ("2026-05-31", "2026-06-01", "2026-06-02"):
            start = pd.Timestamp(f"{day} 00:00")
            for offset in range(80):
                rows.append({
                    "ts": start + timedelta(minutes=offset),
                    "sender": "Farhan" if offset % 2 else "Benazir",
                    "msg": f"message {day} {offset}",
                })

        # A second message at the exact same exported timestamp must survive.
        rows.append({
            "ts": pd.Timestamp("2026-06-02 01:19"),
            "sender": "Benazir",
            "msg": "duplicate timestamp message",
        })
        rows.extend([
            {
                "ts": pd.Timestamp("2026-05-30 23:59"),
                "sender": "Benazir",
                "msg": "outside backward boundary",
            },
            {
                "ts": pd.Timestamp("2026-06-03 00:00"),
                "sender": "Benazir",
                "msg": "outside forward boundary",
            },
        ])
        self.messages_by_timestamp = _build_messages_by_ist_timestamp(
            pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
        )
        self.timestamps = tuple(sorted(self.messages_by_timestamp))

    def test_index_keeps_duplicate_timestamps_in_ist(self):
        duplicate_timestamp = next(
            timestamp
            for timestamp in self.timestamps
            if timestamp.strftime("%Y-%m-%d %H:%M") == "2026-06-02 01:19"
        )

        self.assertEqual(duplicate_timestamp.utcoffset(), timedelta(hours=5, minutes=30))
        self.assertEqual(len(self.messages_by_timestamp[duplicate_timestamp]), 2)

    def test_context_returns_every_message_in_complete_window(self):
        with (
            patch(
                "src.services.chat_context._messages_by_ist_timestamp",
                return_value=self.messages_by_timestamp,
            ),
            patch(
                "src.services.chat_context._sorted_ist_timestamps",
                return_value=self.timestamps,
            ),
        ):
            result = context_for("2026-06-01", days=1)

        self.assertEqual(len(result["messages"]), 241)
        self.assertEqual(
            Counter(message["date"] for message in result["messages"]),
            Counter({"2026-05-31": 80, "2026-06-01": 80, "2026-06-02": 81}),
        )
        self.assertNotIn(
            "outside backward boundary",
            [message["msg"] for message in result["messages"]],
        )
        self.assertNotIn(
            "outside forward boundary",
            [message["msg"] for message in result["messages"]],
        )


if __name__ == "__main__":
    unittest.main()
