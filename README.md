# 🐶 LUVD

**Every new adoptable dog across NYC rescues, on one page, every morning.**

Each rescue is read from its own site where possible, and from the platform it
adopts on otherwise. Dogs you've already been shown never appear again. If
there's nothing new, no email goes out.

## How it works

```
check.py
  ├─ fetch     sources in priority order (own sites → platform APIs)
  ├─ dedupe    within-run (cross-source) + across-run (stable id in SQLite)
  ├─ normalize one shape for every source, so the UI is consistent
  ├─ enrich    3 at-a-glance scores + breed guide grounded in the rescue's words
  ├─ render    public/ — the daily page plus every crawlable page below
  └─ email     Mandrill digest to subscribers, linking to the page
```

## Sources

| Rescue | Priority | How | Status |
|---|---|---|---|
| Muddy Paws Rescue | 10 | public JSON API | ✅ 36 dogs |
| Animal Haven | 11 | server-rendered HTML + detail pages | ✅ 33 dogs |
| Waggytail Rescue | 12 | Petstablished JSON API (via Wix widget) | ✅ 9 dogs |
| Sugar Mutts Rescue | 13 | WordPress | ✅ 6 dogs |
| Sean Casey (24PetConnect) | 14 | server-rendered HTML | ✅ 4 dogs |
| Korean K9 Rescue | 15 | Petstablished org `1956188` | ✅ 29 dogs |
| NYC Second Chance Rescue | 16 | Petstablished org `83716` | ✅ 113 dogs |

230 dogs as of the last run. These move every day as rescues list and adopt out,
so treat the per-rescue numbers as a shape rather than a fact to assert
elsewhere — a run's own output is the only current count.

No credentials are needed for any source. Korean K9's own site sits behind a
Cloudflare challenge and NYC Second Chance's adoptable page is just an iframe of
the Petstablished widget, so both are read from `sources/petstablished.py` — the
public search API behind wagtopia.com, which is the same data their own pages
render. Waggytail is on Petstablished too and could move onto that shared class.

Korean K9 is the one source that splits: Petstablished hands back 31 dogs, but
their own site puts 14 on `/adopt` and 15 on `/foster-to-adopt`, with 2 records
on neither page. `current_location` says which is which, so `KoreanK9Source.route`
tags the foster-to-adopt dogs, points their button at the right application, and
drops the 2 strays. Those dogs are still in South Korea and come home on a 7-day
trial, which is too different from a normal adoption to leave unlabelled — see
"Placement programs" below.

There is no city-wide fallback: that was the Petfinder API, **decommissioned on
2 December 2025** in favour of an embed-only widget. `sources/petfinder.py` is
kept unregistered for reference. Every rescue is now listed explicitly above.

## Setup

```bash
cp .env.example .env
```

Fill in `.env`:

- `MANDRILL_API_KEY` — Mandrill (Mailchimp Transactional); without it nothing is sent
- `SITE_URL` — public URL of the page, used in emails
- `ANTHROPIC_API_KEY` — optional; unlocks LLM-graded scores instead of heuristics
- `SHEET_WEBHOOK_URL` — optional; mirrors subscribers to a Google Sheet (see below)

## Run

```bash
.venv/bin/python check.py --dry-run
```

Fetch everything and rebuild the page without sending email or recording state.

```bash
.venv/bin/python check.py
```

The real morning run: rebuilds the page, records what was shown, emails subscribers.

```bash
.venv/bin/python app.py
```

Serves the page at http://127.0.0.1:8000 and accepts subscribe POSTs.
`GET /subscribers` lists signups.

## The subscriber list, and its backup

SQLite on the Fly volume is the source of truth for `subscribers`. `sheet_sync.py`
additionally mirrors the table to a Google Sheet as an offsite backup, so the
list survives losing the volume.

The mirror is a mirror, never a store. Every sync POSTs the *whole* table to the
Apps Script webhook in `sheet_webhook.gs`, which rewrites the sheet from scratch
— so a missed webhook needs no append/dedup bookkeeping, it just heals on the
next sync. It runs on signup, on unsubscribe, and again nightly at the end of
`check.py`, which is the sweep that closes any gap left by a failed call.

Unset `SHEET_WEBHOOK_URL` and the mirror is skipped entirely; nothing else
changes. The URL is the only credential, so it lives in Fly secrets.

Signup and unsubscribe each have two side effects — the transactional email and
this mirror — and both run on `app.py`'s one background-thread helper
(`_in_background`). Neither can hold a gunicorn worker, and neither can fail the
request or suppress the other: the database write is already committed before
either starts.

## The four emails

Everything goes out through Mandrill, and every message is built in
`emailer.py`.

| Email | Sent when | What's in it |
|---|---|---|
| Welcome | someone subscribes and wasn't already an active subscriber | two lines of copy naming their city, and a montage of four dogs read off a file rather than a live scrape |
| New dogs | the morning run finds dogs nobody has been shown before | up to 6 faces desktop / 4 phone, a count, one button |
| This week's events | Monday's run, per city, if that city has any events in the next seven days | one block per event: what it is, the day, the time, who's running it, where |
| Goodbye | someone unsubscribes, and only the click that actually took them off the list | 3 faces desktop / 2 phone, uncaptioned, and the line "This is the last email you'll get from us" |

Every one of them is city-scoped on both sides — the content and the list it
goes to. An LA subscriber's links all land on `/la`, and the only mail that has
no city is the goodbye, because unsubscribing takes you off every list.

## In-person events

`check_events.py` runs on Monday inside each city's own 05:30 job and mails that
city its week. It is a **separate send from the dog digest, deliberately**:
`check.py` returns before mailing when no dogs arrived overnight, so an events
block folded into that mail would vanish on exactly the quiet Monday it matters
most. Each skips on its own terms, and a city with no events that week sends
nothing at all.

The events come from a Google Sheet, not from scrapers, and that is a measured
decision rather than laziness. A scan of all eleven rescues LUVD follows found
**one** — NYC Second Chance — publishing events in a form anything can read.
Korean K9 runs events and answers 403 to every request, so their site can never
be read. Muddy Paws and Waggytail hide theirs behind an AddEvent widget. Five
publish no events page at all, and Los Angeles has effectively none. A scraped
digest would have been confidently incomplete, which is worse than absent: the
first subscriber who knew about an event we left out would stop trusting the
whole email.

So whatever you learn — a rescue's newsletter, an Instagram post — goes in the
sheet, and the email is complete for both cities. `events.py` reads it:

```bash
.venv/bin/python events.py --print     # parse the sheet, touch nothing
.venv/bin/python events.py --sync      # cache it in SQLite
.venv/bin/python check_events.py --city NYC --dry-run
```

Columns are matched case- and space-insensitively so the sheet stays readable to
a human: `city | rescue | title | date | start | end | location | address | url
| note`. Dates are parsed forgivingly — `2026-08-01`, `8/1/2026`, `Aug 1 2026`
and `Saturday, August 1, 2026` all work.

**When in doubt it does not send.** Mailing several hundred people to an event
that isn't happening is the worst thing this feature can do, so a row is dropped
and reported — never guessed at — when any of these is true:

| Dropped when | Because |
|---|---|
| the date can't be read, including a bare `Aug 1` with no year | guessing the year sends somebody out on a day nothing is happening |
| the title or notes say cancelled, postponed, TBA/TBC or rain date | a sheet is edited by typing, so that is how a cancellation actually arrives — not as a deleted row |
| there is no location *and* no address | an event with a day and no place is not one a reader can act on |
| the city is unknown, or registered but not live | it would be a list nobody is on |
| the row has neither a title nor a rescue | half-entered |

Everything dropped is printed by the run, so a half-finished row gets finished
rather than silently vanishing.

Unset `EVENTS_SHEET_CSV_URL` and the whole feature is skipped; nothing else
changes. A sheet that fails to load leaves the previous cache in place rather
than cancelling the week, and an empty parse never empties the table — an
unreadable sheet means "I don't know", not "cancel everything".

Scrapers can write into the same `events` table later. They are an optimisation,
not the source of truth.

Every footer is the wordmark, with `Unsubscribe` under it on the two that carry
one. Nothing about dates, cadence or why you're receiving it — see HANDOFF.md,
which records what dropping the last of those costs.

The welcome's montage — four tilted polaroids with the dogs' names in the
frame — is a single flat JPEG built by `montage.py`, not HTML. Email cannot
rotate an element or put text over a photo reliably, so the alternative would
have been the same stacked grid the digest already uses. It is regenerated by
the nightly run from dogs currently listed, and the email leaves it out
entirely if the file isn't on disk. The canvas carries a margin of white around
the polaroids on purpose — a JPEG has no transparency, so without it the drop
shadows get cut off square at the edge of the picture. HANDOFF.md has the
geometry, and why the bleed has to be the card's exact `#fff`.

The photo grids are mobile-first on purpose: the two-across phone layout is
what renders by default, and the three-across desktop layout is revealed by a
`min-width:601px` media query. Clients that don't apply media queries — Outlook
on Windows, and the Gmail app signed into a non-Gmail account, which strips the
whole `<style>` block — therefore land on the layout that fits any screen
rather than one that runs off the side of a phone.

No new dogs means no morning email — that's the whole cadence. The welcome and
the goodbye are one-offs, sent from the web process on a daemon thread so a
signup or an unsubscribe never waits on, or fails because of, Mandrill.

The goodbye is the one that has to survive anything: it carries dog photos read
out of the page we last built, and if that file is missing, unreadable or has
no photographed dogs in it, the same email goes out with no grid rather than
with broken images. Its photos have no names under them — the digest's do,
because there someone is deciding which dog to open. It carries no unsubscribe
link and no `List-Unsubscribe` headers — they've already left.

Layout claims in this README ("the grid does not move when you filter", "the
sort's touch target is 44px") are measured against a real browser rather than
eyeballed, using Playwright driving local Chrome. It is installed in `.venv` and
deliberately **not** in `requirements.txt` — it's a development tool, and the
site never imports it. `.venv/bin/pip install playwright` when you need it.
`HANDOFF.md` has the details, including the one measurement trap that produced a
convincing false positive.

## Pages we publish

Every run writes real, crawlable URLs — hash fragments can't be indexed. Flask
resolves the extensionless paths to their `.html` file, and `sitemap.xml` lists
all of them.

| URL | What it is |
|---|---|
| `/`, `/la` | the daily page: one flat grid of every adoptable dog, newest first |
| `/rescues`, `/la/rescues` | that city's roster: every rescue, its dog count, and a link to its own site |
| `/rescue/<slug>` | one rescue's full list — targets "muddy paws rescue dogs" |
| `/dog/<rescue>/<slug>` | one dog, with the rescue's own write-up |

One roster **per city**, not one combined page. "Which dog rescues are in LA?"
is a local question, and a page covering everywhere could only be titled
something like "Dog rescues in NYC and LA" — competing with itself and reading
as a worse answer to either question than a dedicated page. Each roster links
the others at its foot ("Also in Los Angeles →"), which is where the
whole-site view lives. Every link into a roster — the city page's footer, each
rescue page, the JSON-LD breadcrumb — points at the roster for *that page's*
city; `tests/test_multicity.py` fails if any of them points at another city's,
because that bug shipped twice.

`/` and `/rescue/*` carry JSON-LD; each rescue page declares its rescue as an
`AnimalShelter` so answer engines read them as organizations rather than list
rows. The homepage footer and the "Which rescues does LUVD cover?" answer both
link every rescue page — before that they were reachable only from individual
dog pages, which left them effectively unlinked.

Outbound links to a rescue's own site live on that rescue's page and on
its city's roster, deliberately not in the site-wide footer: repeating the same
external links across 230+ pages is a link-scheme pattern, and footer
boilerplate is discounted anyway.

## Finding a dog on the page

One flat grid, newest arrival first. It used to be a section per day with a date
heading on each. That stopped working the moment filters arrived: the database
accumulates a section per day and only sheds one when a rescue delists a dog, so
within a few weeks a narrow filter scattered its handful of matches across a
dozen headings that each announced "1 dog". The arrival date didn't go anywhere —
it is the default sort, and today's dogs carry a NEW HERE marker.

A gentler version was tried and rejected too: keep the flat grid but give
today's arrivals a lead heading, with a second heading for everything else.
Exactly two groups, so they couldn't multiply the way per-day sections did. It
worked, and it still didn't earn its space — two headings stacked under a count
line that already said "230 dogs" put three headings between you and the first
dog, to say something the badge on each new card says where it's actually
useful. It also had to vanish entirely under "Longest waiting", since grouping by
arrival date while ordering by wait length contradicts itself. HANDOFF.md has the
full reasoning; the code is in git history.

What did go with the headings is any stated total. **Nothing on the page says how
many dogs there are except the results count above the grid**, which is why that
line is permanent rather than something a filter conjures up.

### The results count

"230 dogs" — and "90 dogs" once a filter is on. Same sentence either way, only
the number changes. It sits left-aligned directly above the first row of cards,
at **19px/700 on desktop and 17px/700 on phones**. The numeral is at full
contrast and the unit is grey, the same pairing the date and its "N dogs" had.

That 19px is deliberately one step *down* from the retired date headings, which
were 23px on desktop. The count inherited their job when the grid was flattened,
but not their row: it now shares a line with the sort trigger across some 790px
of gap, and at 23px the two ends read as unrelated things that happen to share a
line rather than as one results header.

**Phones take 17px, in step with the rest of the ladder.** Every size on the page
drops across this breakpoint — card names 23 to 19, filter pills 15 to 13.5 — and
the count goes 19 to 17 with them. It has to: 19px is exactly `h3.nm`'s phone
size, so at 19px the count was set in the very type it is a heading for and
competed with the dog names instead of ranking above them. Measured at 390px.
Desktop keeps 19px, where the names are 23px and the count already sits a step
below them.

Shrinking the count to the control size was tried and rejected — it is the only
thing on the page that states how many dogs there are, and at 15px it stops
reading as a heading and becomes metadata.

**The sort trigger is 17px at every width, and does not follow the count.** It
spent a while at the count's 19px, on the theory that the two ends of the results
header should agree. That made the least-used control on the page the loudest
thing in its row, and louder than the four filter pills above it — which are the
controls people actually reach for. The count is the only heading here, so it is
the only thing that moves with the type ladder; the sort is a control and takes
one value at both breakpoints. 17px still sits above the pills' control scale
(15px desktop, 13.5px phones), so it reads as part of the results header rather
than as a fifth filter.

**Its chevron carries its own ratio, deliberately.** The shared `.cv` ratio is
`.72em`; the sort overrides it to `.66em`, drawing an 11.2px arrow against the
pills' 10.8px. The arrow is the least informative mark in the row, so it is the
first thing to give up size — and owning its own ratio means retuning the sort's
type never swings the arrow with it.

**It doesn't say "90 of 230".** The pre-filter total was dropped on purpose: the
pills go solid accent when a filter is on, and clearing one brings the total
straight back, so the second number was spending words on something the controls
were already saying.

It is always on the page. It used to appear only once a filter was applied,
which shoved the entire grid down by the height of the row — roughly 45px — at
the exact instant you clicked, so the confirmation that the filter worked
arrived by moving the thing you were looking at. Permanent means filtering just
changes the number in place.

Nothing in that row comes or goes any more, so there is no shift left to
prevent. For a while it also held a Clear link that appeared with the first
filter, which needed a reserved height to stop the grid dropping as it arrived;
Clear is gone (see below) and the count and the sort are both permanent, so the
row is a constant 44px by construction. Filtering moves the pills, the grid and
the first card by 0.00px, measured at 1440px and 390px.

### Sort by

Sort sits at the right-hand end of that same line. That row is the page's
results header: what you're looking at on the left, the control that reorders it
on the right. It never fills with accent the way a filter pill does, because
something is always sorting and a filled control would claim you'd narrowed the
list.

**It reads "Sort by" and does not show which order is selected** — not even
after you change it. That's unusual, and it's the opposite of the filter pills,
where the gender pill reads "Female" once you pick it. The difference is that
there are two orders and one of them is what you get without touching anything,
so displaying the value spends the widest label in the row to tell you nothing
happened. The menu marks the current order in the accent colour instead. A
conditional version — name the control on the default, name the value once
changed — was built and rejected: a label that changes shape is its own kind of
confusing.

The one thing that is never conditional is the accessible name. The button
always announces "Sort by: Recently added" or "Sort by: Longest waiting". A
sighted person can open the menu and look; a screen reader user can't be left
with a control that only ever says "Sort by".

### The filter row fits a phone now, and says so when it doesn't

For a long time it didn't. Four pills needed 412.7px against the 358px a 390px
phone has, and it was one label's doing: "Foster-to-adopt 15" measured 158.1px,
wider than "Breed" and "Age" put together. **The pill was shortened to
"Foster"**, and all four now fit with the row scrolling nowhere. See "Filters"
below for why only the pill was shortened.

Narrower phones still overflow — 320px is 61px short — so the scroll cue stayed.
A row that scrolls with nothing at its edge just looks like a row that ends,
which would hide the one filter here that isn't a generic pet-site facet. So the
edge with more pills behind it fades out, and the fade disappears when you reach
the end; the same cue in reverse appears on the left once you've scrolled away
from the start. It's keyed on whether the row actually overruns rather than on a
screen width, so it shows up at 320px, stays away at 390px, and would come back
by itself if some future label pushed the row over again. On desktop it never
appears.

It's drawn as a mask rather than as a gradient laid over the row, which means it
can't swallow a tap: every pill stays tappable through it. It also fades to
transparent rather than to a specific colour, so it's correct in both light and
dark without knowing which one is in play — and since the theme here follows NYC
sunrise and sunset rather than the operating system, that matters.

### There is no Clear button

Removing it is deliberate. Clear used to sit beside the count, where an
underlined link next to a heading read as a footnote rather than a control.
Nothing became unreachable: every pill menu opens with "Any breed" / "Any
gender" / "Any age", and Foster is a toggle, so each filter is undone where it
was set.

The one bulk reset that remains is **"Show all dogs"**, inside the "No dogs
match those filters" panel — the only place you can be genuinely stuck, because
an empty grid gives you nothing to judge which pill to loosen. In practice you
can't reach it by clicking: menu options that would return nothing are disabled,
so every click lands on at least one dog. It's there for the state, not the
route.

### Filters

Four pills — Breed, Gender, Age, and a Foster toggle. `breed_group` and
`age_bucket` are derived **server-side** in `page.py` (`breed_group()`,
`age_months()`, `age_bucket()`) and shipped on every dog, so the browser filters
against one fixed vocabulary instead of re-reading "approx 6 1/2 years" in JS.

**Only that pill says "Foster". Everywhere else the program keeps its full name,
"Foster-to-adopt"** — on the dog's card, in the modal, and in the sentence above
the apply button. The short label is on the pill because the long one was the
entire reason the filter row didn't fit a phone, and it's the pill's visible text
only: its accessible name is still "Foster-to-adopt", so a screen reader gets
the unambiguous version. The trade is worth stating plainly, because it is a
real one: "Foster" on its own can be read as fostering temporarily, which is a
different arrangement from fostering with intent to adopt. The chip on each card
is what prevents that reading, so the two can't be separated.

Every option carries a live count, computed against the other active filters but
deliberately not against its own pill, so the numbers in an open menu are
reachable ones and no option can lead to an empty grid. The age buckets carry an
invariant worth keeping: every dog lands in exactly one of Puppy / Young / Adult
/ Senior / **Unknown**, never in none of them, so the options sum to the total
and "Any age" is never larger than its parts. A dog that sits in "Any" and in no
option is a dog you cannot click your way to, and the missing one makes the
arithmetic on screen look broken.

**There are deliberately no behaviour facets** — good with kids, good with dogs,
good with cats, house-trained. Only 3–14% of listings fill those fields in, and
coverage varies wildly across the seven rescues, so a filter on them would report
how thoroughly each rescue types its records rather than which dogs exist. Worse,
hiding a dog because a field is blank misrepresents that dog: absent data is not
a "no". Two clicks would land on a confident, false zero. Petfinder's wall of
facets is the anti-goal, not the target.

### Sort

"Recently added" (default) and "Longest waiting". They key on different fields on
purpose: "Recently added" is `first_seen`, when *LUVD* first saw the dog, and
"Longest waiting" is `waiting_days`, how long the *rescue* has had it listed. A
dog can be new here and have been waiting at its rescue for a year.

**"Longest waiting" silently did nothing for months.** `waiting_days` prefers a
dog's `listed_since` and only falls back to `first_seen`, and `listed_since` was
populated by exactly one thing — the Petfinder integration, decommissioned in
December 2025. After that every dog's `listed_since` was empty, `waiting_days`
was 0 across the board, and the sort reordered nothing at all while looking like
it worked. It is now extracted per source, through one shared parser in
`sources/dates.py`:

| Rescue | `listed_since` comes from |
|---|---|
| Korean K9, NYC Second Chance | Petstablished `created_at` (`sources/petstablished.py`) |
| Waggytail | Petstablished `created_at`, its own org `3856` |
| Sugar Mutts | the WordPress post's publish date |
| Sean Casey | the listing's "Brought to the shelter" field |
| Animal Haven | **nothing** — no date anywhere in the HubSpot/HubDB feed |
| Muddy Paws | **nothing** — the record carries no date field at all |

That's 154 of 230 dogs with a real listing date today. The other 76 are mostly
Animal Haven's and Muddy Paws' rosters, which fall back to `first_seen` — on a
freshly seeded database that is today, so they sort as the *shortest* waits.
That is a floor imposed by missing data, not a claim that those dogs just
arrived, and it's the main caveat on this sort.

`listing_date()` refuses anything it can't stand behind, returning an empty
string rather than a number: unparseable values, dates more than a day in the
future, anything before 2005 (unset columns arrive as the epoch or a placeholder
year), anything older than 12 years (past a large dog's whole life, so it's a
broken record rather than a long wait), and — when the feed also gives a
birthday — a listing date from before the dog was born, which catches a listing
page reused for a second dog of the same name. Petstablished sources also drop
the date for a dog whose previous status was "adopted", since a returned dog's
record long predates the listing you're looking at.

### Badges

Two module-level flags and one string in `page.py` decide what appears on a card:

- **`SHOW_WAIT_BADGE_ON_CARDS = False`.** The hourglass "⏳ Listed N days" badge
  is off on grid cards. Once the scrapers started supplying real listing dates,
  the 60-day threshold put it on 104 of 223 cards and 86 of those were NYC
  Second Chance — three quarters of one rescue's roster. A badge on half the grid
  signals nothing, and concentrated in one rescue it reads as a verdict on them
  rather than a nudge about a dog. It is **still shown** on the dog detail page
  and in the modal, where you're reading one dog and it's a useful fact rather
  than a pattern. Raise `WAIT_BADGE_DAYS` (currently 60) before turning it back
  on; 180 days is still 62 cards.
- **`NEW_MARK_MAX_SHARE = 0.5`.** The NEW marker is suppressed *entirely* when
  more than half the grid arrived today, because a marker on nearly every card
  marks nothing.
- **`NEW_MARK_LABEL = "New here"`.** What that marker says, rendered uppercase.
  It reads as the dog saying it, which matches the voice of the quip bubbles, and
  it is one constant rather than a string copied into three templates — the
  runners-up were "Just in" and "New face". If you swap it, check the width: at
  390px "NEW HERE" already takes 39% of a card, and a longer string will not fit
  without wrapping.

**The consequence of that second flag will confuse you at some point:** on a
freshly seeded database every dog is seen for the first time today, so no NEW
marker renders anywhere on the page. That is the flag working, not a bug. Markers
return on the first day the roster is a mix. If you are looking for them and
finding none, check whether every dog's `first_seen` is today before you go
hunting in the rendering code.

The NEW marker sits on the photo itself, bottom-right — the corner the wait badge
vacated — rather than beside the dog's name. On desktop it disappears while you
hover the card, because the quip bubble that slides up occupies the same corner
and isn't quite wide enough to cover the badge, so its red ends showed on either
side of the white and read as a rendering fault. Hiding the badge rather than
moving it is deliberate: quips are per-dog strings of different lengths and some
wrap to three lines, so any nudge tuned to today's longest quip stops working on
tomorrow's. The rule lives inside the same hover-capable media query as the
bubble, so on a phone — where there is no bubble — the badge never disappears.

## Saved dogs

Hearts on cards keep a list of dog IDs in `localStorage` (`SAVE_KEY`, currently
`luvd:saved`). No account, nothing sent to the server, nothing that survives
clearing the browser. A chip in the header shows the count and toggles a
saved-only view.

The saved view and the main grid deliberately behave **differently** when you
unsave something. In the saved view the grid *is* the list of saved dogs, so
unsaving a dog removes its card immediately, and unsaving the last one reveals
the "No saved dogs yet" empty state. In the main grid, tapping a heart changes
nothing but the heart: the card you just tapped never moves, reflows or
disappears out from under your finger. That asymmetry is the whole design — the
heart handler calls `applyView()` only when `showingSaved` is true.

Entering the saved view **clears any active filters**; leaving it **puts them
back**. The two directions differ on purpose. Going in, a saved list is a
handful of dogs, and leaving pills applied behind a filter bar that's just been
hidden would silently shorten it — you'd see four of your six saved dogs with
nothing on screen explaining the other two. Coming out, those filters were a
search you were part-way through, and glancing at a saved dog shouldn't cost you
your place in it. The sort order survives throughout; it is never cleared.

## Placement programs

Not every dog is a plain adoption. A `Dog` can carry a `program` (`program_label`
for the chip, `program_note` for the terms), which changes three things in the UI:
an amber pill leads the card ahead of breed, a matching chip leads the modal, and
the note sits directly above the apply button — the one place someone can't miss
it before they click.

The only program today is Korean K9's foster-to-adopt, where the dog hasn't left
South Korea yet: you meet them for the first time at pickup, take them home for a
7-day trial, and keep fostering ~3 weeks if it isn't a fit. The button goes to
their foster-to-adopt page rather than the form behind it, because the arrival
date each application is timed against (applications close 48 hours before) is
only published on the page.

The rule of thumb for adding one: if a listing needs a different application or
asks for a materially different commitment, it's a program, not a trait.

## The three scores

Each dog gets **Energy**, **Apartment fit** and **Experience needed** (1–5), shown as
bars in the modal. They're derived from breed tendencies in `breeds.json` adjusted by
keyword signals in the rescue's own write-up — a third of dogs have breed "Unknown",
so the bio does most of the work.

These are **estimates and labelled as such in the UI.** The rescue is the source of
truth on any individual animal.

## View counts (🔥 badges)

Cards show a fire badge with how many people have opened that dog's modal. These
are **real counts**, stored server-side (`POST /view`, read via `GET /views`), and
they only appear once a dog passes `VIEW_FLOOR` (3) so the number means something.

On static hosting with no backend, the badges simply never render — the page never
invents a number. Fake urgency would contradict the product's own promise.

## Similar dogs

Each modal ends with a "More dogs like <name>" row, scored client-side from data
already on the page: same breed weighs most, then how closely the three ratings
line up, then shared traits and size. Each suggestion shows *why* it matched, and
matches cross rescue boundaries — a Muddy Paws dog can surface under an Animal
Haven one.

## Easter egg

Hovering the logo drifts paw prints upward; clicking it sets off a burst, and
every fifth click earns a woof. Respects `prefers-reduced-motion`.

## Adding a rescue

1. Copy `sources/rescues/_template.py` to `sources/rescues/<name>.py`.
2. Return `Dog` objects with a **stable id** (dedup depends on it).
3. Register it in `sources/registry.py` under `_DIRECT` with a priority below 900.

Normalization and scoring happen centrally, so a new scraper only has to fetch.

## Not done yet

- **Hosting.** Runs locally; no cron yet. Needs a host + daily schedule.

- **Breed data.** Roughly a third of dogs come through with breed "Unknown" —
  Muddy Paws in particular. The scores lean on the write-up to compensate.
