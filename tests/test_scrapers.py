"""Offline regressions for the live roster audit of 2026-10-03."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sources.adoptapet import AdoptAPetSource, _json_array
from sources.petstablished import PetstablishedSource
from sources.rescues.koreank9 import KoreanK9Source
from sources.base import Dog, Source
import check


def flight(payload):
    return '<script>self.__next_f.push([1,' + json.dumps(json.dumps(payload)) + '])</script>'


def card(pid, name='Dog', species=1):
    return {'petId': pid, 'name': name, 'clanId': species, 'adopted': False,
            'pdpRoute': f'https://www.adoptapet.com/pet/{pid}-test',
            'description': 'A dog [with a note] loves walks.', 'photoUrl': 'https://example.org/photo.jpg'}


def roster(records, current=1, last=1):
    return flight({'availablePets': records, 'paginatorInfo': {
        'currentPage': current, 'lastPage': last, 'total': len(records)}})


class AdoptAPetTests(unittest.TestCase):
    def source(self):
        s = AdoptAPetSource(); s.shelter_path = 'shelter/123-test'; s.pause = 0
        return s

    def test_all_pages_without_recommendations_or_cats(self):
        s = self.source()
        pages = [roster([card(1), card(2, species=2)], 1, 2) +
                 '<a href="https://www.adoptapet.com/pet/999-nearby">Nearby</a>',
                 roster([card(3), card(1)], 2, 2)]
        with patch.object(s, '_get', side_effect=pages) as get:
            rows = s._roster_records()
        self.assertEqual([x['petId'] for x in rows], [1, 3])
        self.assertTrue(get.call_args_list[1].args[0].endswith('?page=2'))

    def test_pagination_failure_is_not_partial_success(self):
        s = self.source()
        for last in [None, roster([card(1)], 1, 2)]:
            with patch.object(s, '_get', side_effect=[roster([card(1)], 1, 2), last]):
                with self.assertRaises((RuntimeError, ValueError)):
                    s._roster_records()

    def test_missing_roster_is_not_an_empty_shelter(self):
        s = self.source()
        with patch.object(s, '_get', return_value=flight({'pets': [card(99)]})):
            with self.assertRaises(ValueError): s._roster_records()

    def test_brackets_in_prose(self):
        rows = [card(1), card(2, 'Name ] with bracket')]
        self.assertEqual(_json_array(json.dumps({'availablePets': rows}), 'availablePets'), rows)

    def test_empty_detail_keeps_available_roster_dog(self):
        s = self.source()
        with patch.object(s, '_get', side_effect=[roster([card(1, 'Rachel')]), '']):
            dogs = s.fetch({})
        self.assertEqual([d.name for d in dogs], ['Rachel'])
        self.assertEqual(dogs[0].photos, ['https://example.org/photo.jpg'])
        self.assertEqual(s.detail_warnings, ['1'])

    def test_newly_pending_detail_is_excluded(self):
        s = self.source()
        detail = flight({'petId': 1, 'petName': 'Dog', 'petSpeciesId': 1, 'petState': 'pending'})
        with patch.object(s, '_get', side_effect=[roster([card(1)]), detail]):
            self.assertEqual(s.fetch({}), [])


class PetstablishedTests(unittest.TestCase):
    def test_truncated_pagination_rejected(self):
        s = PetstablishedSource(); s.org_id = '1'
        with patch.object(s, '_get', side_effect=[{'pets': [{'id': 1}], 'total_page': 2}, {'pets': [], 'total_page': 2}]), patch('sources.petstablished.time.sleep'):
            with self.assertRaises(ValueError): s.fetch({})

    def test_malformed_detail_is_not_blank_location(self):
        s = KoreanK9Source()
        with patch.object(s, '_get', return_value={'pet': {}}):
            self.assertIsNone(s._detail(None, Dog('koreank9:1', 'Dog', 'koreank9', 'KK', 'url')))

    def test_pending_detail_overrides_stale_search(self):
        s = PetstablishedSource()
        dog = Dog('test:1', 'Dog', 'test', 'Test', 'url')
        with patch.object(s, '_detail', return_value={'id': 1, 'status': 'Pending'}):
            self.assertEqual(s._walk_details(None, [dog]), [])

    def test_cookie_rechecked_and_not_forced_if_unavailable(self):
        s = KoreanK9Source()
        base = {'id': 2721643, 'name': 'Cookie', 'animal': 'Dog', 'shelter_id': 1956188,
                'current_location': '2: East Coast Dogs', 'status': 'Available'}
        for status, expected in [('Available', 1), ('Pending', 0), ('Adopted', 0)]:
            with patch.object(PetstablishedSource, 'fetch', return_value=[]), patch.object(s, '_get', return_value={'pet': dict(base, status=status)}):
                dogs = s.fetch({})
                self.assertEqual(len(dogs), expected)
                if dogs: self.assertEqual(dogs[0].id, 'koreank9:2721643')

    def test_cookie_not_duplicated_when_feed_recovers(self):
        s = KoreanK9Source()
        dog = Dog('koreank9:2721643', 'Cookie', 'koreank9', 'KK', 'url')
        with patch.object(PetstablishedSource, 'fetch', return_value=[dog]), patch.object(s, '_get') as get:
            self.assertEqual(s.fetch({}), [dog]); get.assert_not_called()


class OutageTests(unittest.TestCase):
    def test_failed_rescue_keeps_its_published_program_and_city(self):
        s = Source(); s.name = 'test'; s.city = 'LA'; s.fetch = MagicMock(side_effect=RuntimeError('offline'))
        cached = {'id': 'test:1', 'name': 'Dog', 'source': 'test', 'source_label': 'Test', 'url': 'https://example.org',
                  'program': 'foster-to-adopt', 'program_note': 'Trial', 'cta_url': 'https://example.org/foster'}
        with patch.object(check, 'sources_for_city', return_value=[s]), patch('emailer._page_dogs', return_value={'test:1': cached}):
            dogs, failures = check.collect({}, 'LA', verbose=False)
        self.assertEqual(dogs[0].program, 'foster-to-adopt')
        self.assertEqual(dogs[0].city, 'LA')
        self.assertEqual(dogs[0].adopt_url, 'https://example.org/foster')
        self.assertEqual(check._failed_names(failures), {'test'})

    def test_all_outages_do_not_republish_cached_data_as_fresh(self):
        dog = Dog('test:1', 'Dog', 'test', 'Test', 'url')
        with patch.object(check.db, 'init_db'), patch.object(check.db, 'get_prefs', return_value={}), \
             patch.object(check, 'collect', return_value=([dog], ['test (offline)'])), \
             patch.object(check, '_alert'), patch.object(check.page, 'write') as write, \
             patch.object(check.db, 'record_seen') as record:
            self.assertEqual(check.run(city='NYC'), [])
            write.assert_not_called()
            record.assert_not_called()

    def test_outage_sources_cannot_be_pruned_or_announced(self):
        from contextlib import ExitStack
        import push
        fresh = Dog('good:1', 'Fresh', 'good', 'Good', 'url', city='LA')
        cached = Dog('bad:1', 'Cached', 'bad', 'Bad', 'url', city='LA')
        with ExitStack() as stack:
            def stub(obj, key, **kwargs):
                return stack.enter_context(patch.object(obj, key, **kwargs))
            stub(check.db, 'init_db')
            stub(check.db, 'get_prefs', return_value={})
            stub(check, 'collect', return_value=([fresh, cached], ['bad (offline)']))
            stub(check, '_alert')
            stub(check, 'sources_for_city', return_value=[])
            stub(check, 'normalize', side_effect=lambda ds: ds)
            stub(check, 'enrich', side_effect=lambda ds: ds)
            stub(check.db, 'first_seen_map', return_value={fresh.id: '2020-01-01'})
            stub(check.db, 'record_seen', return_value={fresh.id: '2020-01-01'})
            stub(check.db, 'count_seen', return_value=2)
            forget = stub(check.db, 'forget_missing', return_value=0)
            stub(check.db, 'photo_state', return_value={})
            stub(check.db, 'update_photo_state')
            stub(check, '_passive_pages', return_value={})
            stub(check.page, 'write', return_value='test page')
            announce = stub(push, 'send_new_dogs')
            check.run(city='LA')
            self.assertEqual(forget.call_args.kwargs['sources'], {'good'})
            announce.assert_not_called()


if __name__ == '__main__': unittest.main()
