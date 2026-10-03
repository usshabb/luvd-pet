"""Read-only scraper health audit. Never renders, records dogs, or sends messages.

Usage: .venv/bin/python tools/check_scrapers.py [--city NYC] [--source koreank9]
       [--output /path/to/report.json]
Exit 1 means an empty/failed roster; exit 2 means detail pages degraded.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sources.registry import all_sources


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--city', choices=['NYC', 'LA'])
    parser.add_argument('--source')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    sources = [s for s in all_sources() if (not args.city or s.city == args.city)
               and (not args.source or s.name == args.source)]
    if not sources:
        parser.error('no matching source')
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'sources': []}
    for source in sources:
        started = time.monotonic()
        row = {'source': source.name, 'city': source.city}
        try:
            dogs = source.fetch({})
            details = getattr(source, 'detail_warnings', [])
            row.update(status='empty' if not dogs else 'degraded' if details else 'ok',
                       count=len(dogs), ids=[d.id for d in dogs],
                       missing_photos=sum(not d.photos for d in dogs),
                       missing_description=sum(not d.description for d in dogs),
                       detail_failures=details)
        except Exception as exc:
            row.update(status='error', error=f'{type(exc).__name__}: {exc}')
        row['seconds'] = round(time.monotonic() - started, 1)
        report['sources'].append(row)
        print(json.dumps(row), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    statuses = {r['status'] for r in report['sources']}
    return 1 if statuses & {'error', 'empty'} else 2 if 'degraded' in statuses else 0


if __name__ == '__main__':
    sys.exit(main())
