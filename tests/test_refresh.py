"""Refresh timing, first-observation dates, and opt-in push delivery regressions."""
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check
import db
import emailer
import push
from refresh_schedule import next_action
from sources.base import Dog
from sources.adoptapet import AdoptAPetSource
from sources.petstablished import PetstablishedSource


def dog(id='test:1'):
    return Dog(id, 'New Dog', 'test', 'Test', 'https://example.org/dog',
               city='LA', first_seen='2026-10-02')


class ScheduleTests(unittest.TestCase):
    def test_quarter_hour_poll(self):
        self.assertEqual(next_action(0, 5000, 0, 0), (900, 'roster'))
    def test_hourly_full_wins_tie(self):
        self.assertEqual(next_action(3600, 5000, 2700, 0), (0, 'full'))
    def test_overdue_morning_cannot_be_skipped(self):
        self.assertEqual(next_action(5100, 5000, 0, 0), (0, 'daily'))
    def test_morning_wins_a_tie(self):
        self.assertEqual(next_action(0, 900, 0, 0), (900, 'daily'))
    def test_no_zero_or_inverted_intervals(self):
        with self.assertRaises(ValueError): next_action(0, 1, 0, 0, 0, 1)
        with self.assertRaises(ValueError): next_action(0, 1, 0, 0, 900, 10)


class QuickPollTests(unittest.TestCase):
    def test_known_adoptapet_dog_needs_no_detail_call(self):
        s = AdoptAPetSource(); s.name = 'test'; s.shelter_path = 'shelter/1-test'
        old = dog(); old.program = 'foster-to-adopt'
        row = {'petId': 1, 'pdpRoute': 'https://www.adoptapet.com/pet/1-test'}
        with patch.object(s, '_roster_records', return_value=[row]), patch.object(s, '_get') as get:
            found = s.fetch({'_roster_only': True, '_cached_dogs': {old.id: old}})
        get.assert_not_called()
        self.assertEqual(found[0].program, 'foster-to-adopt')
        self.assertIsNot(found[0], old)

    def test_petstablished_new_dog_still_gets_verified(self):
        s = PetstablishedSource(); old = dog(); new = dog('test:2')
        with patch.object(s, '_detail', return_value={'id': 2, 'status': 'Available'}) as detail, patch('sources.petstablished.time.sleep'):
            found = s._walk_details(None, [old, new], {'_roster_only': True, '_cached_dogs': {old.id: old}})
        self.assertEqual(len(found), 2)
        self.assertEqual(detail.call_count, 1)
        self.assertEqual(detail.call_args.args[1].id, new.id)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(db, 'DB_PATH', Path(self.tmp.name)/'test.db')
        self.path_patch.start(); db.init_db()
    def tearDown(self):
        self.path_patch.stop(); self.tmp.cleanup()

    def test_preserves_first_observation_at_next_morning(self):
        d = dog()
        dates = db.record_seen([d], '2026-10-03')
        self.assertEqual(dates[d.id], '2026-10-02')

    def test_push_opt_in_and_receipts(self):
        db.add_device('morning', 'LA'); db.add_device('instant', 'LA')
        db.set_instant_updates('instant', True)
        d = dog()
        with patch.object(push, 'configured', return_value=True), patch.dict(os.environ, {'PUSH_PAUSED': ''}), \
             patch.object(push, 'send', return_value={'sent': 1, 'failed': 0, 'dead': []}) as send:
            push.send_new_dogs('LA', [d], client=object(), instant_only=True)
            self.assertEqual(send.call_args.args[0], [('instant', 'production')])
            self.assertIsNone(push.send_new_dogs('LA', [d], client=object(), instant_only=True))
            self.assertEqual(send.call_count, 1)
            push.send_new_dogs('LA', [d], client=object())
            self.assertEqual(send.call_args.args[0], [('morning', 'production')])
            self.assertEqual(send.call_count, 2)

    def test_failed_delivery_retries_without_repeating_success(self):
        for token in ['a', 'b']:
            db.add_device(token, 'LA'); db.set_instant_updates(token, True)
        def result(devices, *args, **kwargs):
            return {'sent': int(devices[0][0] == 'a'), 'failed': int(devices[0][0] == 'b'), 'dead': []}
        with patch.object(push, 'configured', return_value=True), patch.dict(os.environ, {'PUSH_PAUSED': ''}), \
             patch.object(push, 'send', side_effect=result) as send:
            push.send_new_dogs('LA', [dog()], client=object(), instant_only=True)
            send.reset_mock()
            push.send_new_dogs('LA', [dog()], client=object(), instant_only=True)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.args[0], [('b', 'production')])

    def test_refresh_never_emails_and_morning_includes_yesterdays_discovery(self):
        db.add_subscriber('test@example.invalid', 'LA')
        d = dog()
        with ExitStack() as stack:
            def stub(obj, key, **kw): return stack.enter_context(patch.object(obj, key, **kw))
            stub(check, 'collect', return_value=([d], []))
            stub(check, '_published_dates', return_value={d.id: '2026-10-02'})
            stub(check.cities, 'today', return_value=date(2026, 10, 3))
            stub(check, 'sources_for_city', return_value=[])
            stub(check, '_alert')
            stub(check, '_passive_pages', return_value={})
            stub(check, 'normalize', side_effect=lambda ds: ds)
            stub(check, 'enrich', side_effect=lambda ds: ds)
            stub(check.page, 'write', return_value='test page')
            notify = stub(push, 'send_new_dogs')
            mail = stub(emailer, 'send_digest')
            stack.enter_context(patch.dict(os.environ, {'EMAILS_PAUSED': ''}))
            check.run(city='LA', refresh=True, roster_only=True)
            mail.assert_not_called()
            self.assertEqual(db.first_seen_map([d.id]), {})
            self.assertTrue(notify.call_args.kwargs['instant_only'])
            check.run(city='LA')
            self.assertEqual(mail.call_count, 1)
            self.assertEqual(mail.call_args.args[1][0].id, d.id)
            self.assertEqual(db.first_seen_map([d.id])[d.id], '2026-10-02')


if __name__ == '__main__': unittest.main()
