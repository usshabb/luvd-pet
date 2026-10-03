"""Published assets remain usable; stale/failed scrapes cannot report healthy."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db
import page
import emailer
import scraper_health as health
from sources.base import Dog


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(db, 'DB_PATH', Path(self.tmp.name)/'test.db'),
                        patch.object(health.cities, 'live_codes', return_value=['NYC','LA'])]
        for p in self.patches: p.start()
    def tearDown(self):
        for p in self.patches: p.stop()
        self.tmp.cleanup()

    def seed(self):
        for city in ['NYC','LA']:
            health.checked(city, [], now=10000)
            health.published(city, now=10000)

    def test_missing_failed_and_stale_are_unhealthy(self):
        self.assertFalse(health.status(10000)['ok'])
        self.seed()
        self.assertTrue(health.status(10001)['ok'])
        health.checked('LA', ['one rescue failed'], now=10002)
        self.assertFalse(health.status(10003)['ok'])
        health.checked('LA', [], now=10004)
        self.assertTrue(health.status(10005)['ok'])
        # A check is not a completed publish; repeated checks cannot hide a stuck render.
        health.checked('NYC', [], now=14000)
        health.checked('LA', [], now=14000)
        self.assertTrue(health.status(14000)['cities']['NYC']['stale'])

    def test_alert_throttle_and_failure_retry(self):
        with patch.dict(os.environ, {'ALERT_EMAIL':'operator@example.invalid'}), \
             patch.object(emailer, 'email_configured', return_value=True), \
             patch.object(emailer, 'send_email') as send:
            send.side_effect = RuntimeError('offline')
            self.assertFalse(health.alert('broken', 'details'))
            send.side_effect = None
            self.assertTrue(health.alert('broken', 'details'))
            self.assertFalse(health.alert('broken', 'details'))
            self.assertEqual(send.call_count, 2)

    def test_watchdog_grace_and_healthy_recovery(self):
        with patch.object(health, 'alert') as notify:
            health.watchdog_once(now=10000, started=9990)
            notify.assert_not_called()
            health.watchdog_once(now=14000, started=9990)
            self.assertEqual(notify.call_count, 2)
            self.seed(); notify.reset_mock()
            health.watchdog_once(now=10001)
            notify.assert_not_called()

    def test_first_checked_city_waits_for_combined_initial_publish(self):
        # Reproduce the production email: NYC checked successfully, LA still
        # collecting, and neither city has completed its initial publication.
        health.checked('NYC', [], now=10100)
        with patch.object(health, 'alert') as notify:
            snapshot = health.watchdog_once(now=10300, started=10000)
            self.assertFalse(snapshot['ok'])  # endpoint remains honest
            notify.assert_not_called()
            # A hung initial publish must eventually alert despite fresh checks.
            health.checked('NYC', [], now=12700)
            health.watchdog_once(now=12701, started=10000)
            self.assertEqual(notify.call_count, 2)

    def test_startup_grace_does_not_hide_source_failures_or_stale_publish(self):
        health.checked('NYC', ['rescue failed'], now=10100)
        with patch.object(health, 'alert') as notify:
            health.watchdog_once(now=10300, started=10000)
            self.assertEqual(notify.call_count, 1)
            self.assertEqual(notify.call_args.kwargs['key'], 'health:NYC')
        self.seed()
        with patch.object(health, 'alert') as notify:
            health.watchdog_once(now=14000, started=13990)
            self.assertEqual(notify.call_count, 2)  # restart cannot hide stale data

    def test_endpoint_status_and_cache(self):
        import app
        with app.app.test_client() as client:
            response = client.get('/health/scrapers')
            self.assertEqual(response.status_code, 503)
            self.seed()
            with patch.object(health.time, 'time', return_value=10001):
                response = client.get('/health/scrapers')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertNotIn('failures', response.json['cities']['NYC'])


class AssetTests(unittest.TestCase):
    def test_roster_readers_and_hashed_assets_survive_refresh(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(page, 'OUT_DIR', Path(tmp)), \
             patch.object(emailer, 'PUBLIC', Path(tmp)):
            d = Dog('test:1', 'Pup', 'test', 'Test', 'https://example.org/dog',
                    description='Unicode 🐶 and </script> safely in data',
                    photos=['https://example.org/photo.jpg'], city='NYC')
            original = page.render([d], date(2026,10,3), 'NYC')
            optimized = page._cache_city_assets(original)
            (Path(tmp)/'index.html').write_text(optimized)
            self.assertEqual(emailer._page_dogs('NYC')[d.id]['description'], d.description)
            self.assertIn('loading="eager" fetchpriority="high"', optimized)
            self.assertNotIn('<style>', optimized)
            self.assertLess(len(optimized), len(original)-100000)
            assets = re.findall(r'/assets/generated/[a-f0-9]{20}\.(?:js|css)', optimized)
            self.assertEqual(len(assets), 2)
            for url in assets: self.assertTrue((Path(tmp)/url.lstrip('/')).is_file())
            d.description = 'Changed roster data'
            second = page._cache_city_assets(page.render([d], date(2026,10,4), 'NYC'))
            self.assertEqual(assets, re.findall(r'/assets/generated/[a-f0-9]{20}\.(?:js|css)', second))
            self.assertIn('about every 15 minutes', optimized)
            self.assertNotIn('updated every morning', optimized)
            import app
            with patch.object(app, 'PUBLIC', Path(tmp)), app.app.test_client() as client:
                r = client.get(assets[0])
                self.assertEqual(r.status_code, 200)
                self.assertIn('immutable', r.headers['Cache-Control'])
                self.assertEqual(client.get('/assets/generated/'+'a'*20+'.js').status_code, 404)


if __name__ == '__main__': unittest.main()
