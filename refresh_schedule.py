"""Plan serialized roster polls, full refreshes, and the fixed morning digest."""
import argparse
import os
import time

ROSTER_INTERVAL = 15 * 60
DETAIL_INTERVAL = 60 * 60


def next_action(now, daily_due, last_roster, last_full,
                roster_interval=ROSTER_INTERVAL, detail_interval=DETAIL_INTERVAL):
    if roster_interval <= 0 or detail_interval < roster_interval:
        raise ValueError('refresh intervals must be positive; details cannot be more frequent than rosters')
    # Morning wins ties and overdue work, so a slow poll cannot skip a digest.
    if now >= daily_due:
        return 0, 'daily'
    full_due = last_full + detail_interval
    roster_due = last_roster + roster_interval
    if now >= full_due:
        return 0, 'full'
    if now >= roster_due:
        return 0, 'roster'
    due, _, action = min((daily_due, 0, 'daily'), (full_due, 1, 'full'),
                         (roster_due, 2, 'roster'))
    return max(0, int(due - now)), action


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--daily-due', type=int, required=True)
    parser.add_argument('--last-roster', type=int, required=True)
    parser.add_argument('--last-full', type=int, required=True)
    args = parser.parse_args()
    wait, action = next_action(int(time.time()), args.daily_due,
                              args.last_roster, args.last_full,
                              int(os.getenv('LUVD_ROSTER_INTERVAL_SECONDS', ROSTER_INTERVAL)),
                              int(os.getenv('LUVD_DETAIL_INTERVAL_SECONDS', DETAIL_INTERVAL)))
    print(wait, action)


if __name__ == '__main__':
    main()
