import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException

from app.schemas.blackout import BlackoutCreate, EquipmentBlackoutCreate
from app.services.blackout_service import expand_weekday_occurrences


class BlackoutWeekdayTests(unittest.TestCase):
    def test_weekdays_expand_to_daily_intervals_in_range(self):
        start = datetime(2026, 11, 2, 8)
        end = datetime(2026, 11, 6, 18)
        occurrences = expand_weekday_occurrences(start, end, [0, 1, 2, 3, 4])
        self.assertEqual(len(occurrences), 5)
        self.assertEqual([row[0].weekday() for row in occurrences], [0, 1, 2, 3, 4])
        self.assertTrue(all(row[0].hour == 8 and row[1].hour == 18 for row in occurrences))

    def test_weekend_selection_expands_only_selected_days(self):
        occurrences = expand_weekday_occurrences(
            datetime(2026, 11, 2, 9),
            datetime(2026, 11, 8, 17),
            [5, 6],
        )
        self.assertEqual([row[0].weekday() for row in occurrences], [5, 6])

    def test_one_time_blackout_preserves_full_interval(self):
        start = datetime(2026, 11, 2, 9)
        end = datetime(2026, 11, 4, 17)
        self.assertEqual(expand_weekday_occurrences(start, end, []), [(start, end)])

    def test_rejects_ranges_without_selected_weekday(self):
        with self.assertRaises(HTTPException):
            expand_weekday_occurrences(
                datetime(2026, 11, 2, 9),
                datetime(2026, 11, 2, 17),
                [4],
            )

    def test_rejects_overnight_repeating_windows_and_ranges_over_one_year(self):
        with self.assertRaises(HTTPException):
            expand_weekday_occurrences(
                datetime(2026, 11, 2, 18),
                datetime(2026, 11, 6, 8),
                [0, 1, 2, 3, 4],
            )
        with self.assertRaises(HTTPException):
            expand_weekday_occurrences(
                datetime(2026, 1, 1, 8),
                datetime(2027, 1, 2, 18),
                [0],
            )

    def test_schemas_deduplicate_weekdays_and_equipment_ids(self):
        common = {
            "start_datetime": datetime(2026, 11, 2, 8),
            "end_datetime": datetime(2026, 11, 2, 18),
            "repeat_weekdays": [4, 0, 4],
            "reason_explanation": "Weekly facility maintenance",
        }
        resource = BlackoutCreate(resource_ids=[2, 2], **common)
        equipment = EquipmentBlackoutCreate(equipment_ids=[7, 7], **common)
        self.assertEqual(resource.repeat_weekdays, [0, 4])
        self.assertEqual(resource.resource_ids, [2])
        self.assertEqual(equipment.repeat_weekdays, [0, 4])
        self.assertEqual(equipment.equipment_ids, [7])


if __name__ == "__main__":
    unittest.main()
