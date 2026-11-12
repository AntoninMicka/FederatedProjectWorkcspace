# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from spikes.composable_monitoring import processing_slot


class ProcessingCalendarTests(unittest.TestCase):
    def slot(self, kind, value, time='07:00'):
        instant = datetime.fromisoformat(value).timestamp()
        return processing_slot(dict(kind=kind, time=time, timezone='Europe/Prague'), instant)

    def test_calendar_boundaries_and_start_time(self):
        for kind, before, after, expected in (
            ('daily', '2026-11-12T06:59:00+01:00', '2026-11-12T07:00:00+01:00', '2026-11-12'),
            ('weekly', '2026-11-09T06:59:00+01:00', '2026-11-09T07:00:00+01:00', '2026-11-09'),
            ('monthly', '2026-12-01T06:59:00+01:00', '2026-12-01T07:00:00+01:00', '2026-12-01'),
            ('quarterly', '2026-10-01T06:59:00+02:00', '2026-10-01T07:00:00+02:00', '2026-10-01'),
            ('annual', '2027-01-01T06:59:00+01:00', '2027-01-01T07:00:00+01:00', '2027-01-01')):
            with self.subTest(kind=kind):
                self.assertIsNone(self.slot(kind, before))
                self.assertEqual(self.slot(kind, after), expected)
        self.assertEqual(self.slot('weekly', '2026-11-12T01:00:00+01:00'), '2026-11-09')
        self.assertEqual(self.slot('monthly', '2028-02-29T23:00:00+01:00'), '2028-02-01')
        self.assertEqual(self.slot('quarterly', '2026-12-31T23:59:00+01:00'), '2026-10-01')
        self.assertIsNone(self.slot('manual', '2026-11-12T12:00:00+01:00'))

    def test_dst_has_one_calendar_slot_and_no_seconds_based_drift(self):
        first = datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo('Europe/Prague'), fold=0)
        second = first.replace(fold=1)
        self.assertNotEqual(first.timestamp(), second.timestamp())
        schedule = dict(kind='daily', time='02:30', timezone='Europe/Prague')
        self.assertEqual(processing_slot(schedule, first.timestamp()), '2026-10-25')
        self.assertEqual(processing_slot(schedule, second.timestamp()), '2026-10-25')
        self.assertIsNone(self.slot('daily', '2026-03-29T01:59:00+01:00', '02:30'))
        self.assertEqual(self.slot('daily', '2026-03-29T03:00:00+02:00', '02:30'), '2026-03-29')
