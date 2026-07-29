# LUVD NYC — handoff

A daily-updating page of every adoptable dog across NYC rescues.
Python + Flask + SQLite, containerised. `DEPLOY.md` is the step-by-step.

## Deploy in one line

```bash
./deploy.sh <server-ip> luvd.com <ssh-key.pem>
```

Targets a fresh Ubuntu box (AWS Lightsail $5/mo recommended). Installs Docker,
uploads, builds, starts Caddy with automatic HTTPS, seeds the first scrape,
verifies. Refuses to run if DNS hasn't propagated — Let's Encrypt rate-limits
failed certificate attempts.

## Architecture

| Piece | What it does |
|---|---|
| `check.py` | The nightly job. Fetch → dedupe → date → enrich → render → email. |
| `sources/` | One module per rescue. Each fails independently. |
| `normalize.py` | Forces every source into one shape so the UI is consistent. |
| `enrich.py` | The four ratings + breed guide, from the rescue's text and `breeds.json`. |
| `page.py` | Renders everything in `public/` — the daily page, `/rescues`, and a page per rescue and per dog. No framework, no build step. |
| `app.py` | Serves the page + `/subscribe`, `/view`, `/img`, `/sitemap.xml`. |
| `og_image.py` | Rebuilds the 1200×630 social card nightly. |
| `db.py` | SQLite. **The only stateful thing here.** |

Three containers: `web` (gunicorn), `cron` (sleeps until 05:30 ET), `caddy` (TLS).

## The one thing that must not be lost

`/data/dogfinder.db` on the `luvd-data` volume. It holds:

- **`first_seen`** — which day each dog appeared. This *is* the timeline; lose
  it and every dog reads as "new today".
- **`subscribers`** — the email list.
- **`dog_views`** — the 🔥 counts.

None of it is reproducible from the rescues. Back it up:

```bash
docker run --rm -v luvd_luvd-data:/d -v $PWD:/b alpine \
  tar czf /b/luvd-backup-$(date +%F).tgz -C /d .
```

## Environment

Copy `.env.example` → `.env`. Required to be fully live:

| Var | Effect if missing |
|---|---|
| `LUVD_DOMAIN` | Caddy won't start |
| `SITE_URL` | Emails and OG tags point at localhost |
| `RESEND_API_KEY` | **No email sends at all** (signups still captured) |
| `ALERT_EMAIL` | Scraper failures are silent |
| `ANTHROPIC_API_KEY` | Optional — upgrades breed-guide text |

## Adding keys after launch

Resend is optional at deploy time and can be added any day after. No rebuild —
`env_file` is read when the container starts:

```bash
nano /opt/luvd/.env          # add the key(s)
docker compose up -d         # recreates containers with the new env
docker compose run --rm cron python check.py   # optional: apply immediately
```

**Until Resend is added:** signups are still captured to the database — they
just don't receive anything yet. Whoever subscribes on day one gets their first
email the morning after the key lands. Nothing is lost. Scraper failure alerts
are also silent until then.

Verified: a full nightly run with **no keys at all** exits 0, builds the page
and the share card, and only logs that email couldn't send. No key is needed to
fetch dogs — every rescue source is a public endpoint.

## Known state

**Working:** 7 scrapers, 230 dogs. Muddy Paws (JSON API), Animal Haven (HTML +
detail pages), Waggytail (Petstablished API), Sugar Mutts (HTML), Sean Casey
(HTML), Korean K9 (Petstablished org `1956188`, routed by location — see below),
NYC Second Chance (Petstablished org `83716`, with per-dog trait flags). The dog
count moves daily; a run's own output is the only current one.

**The page is one flat grid.** The per-day sections and their date headings are
gone — they didn't survive filters, which scattered a few matches across a dozen
headings each announcing "1 dog". Above the grid: four filter pills (Breed,
Gender, Age, Foster-to-adopt) on their own centred row, then a results header
with the count on the left and the sort control on the right. `breed_group` and
`age_bucket` are computed server-side in `page.py` and shipped on each dog.
`applyView()` is the single source of truth for which cards are visible — the
filters, the sort and the saved view all run through it, because two functions
each setting card display would take turns undoing each other.

**The count line is the page's only statement of a total** now that the date
headings are gone, which is why it is permanently visible rather than appearing
on first filter. It reads `N dogs` and nothing else — the same sentence filtered
or not, only the number changing. **It deliberately does not say "N of M".** The
pills go solid accent when a filter is on and clearing one brings the total
straight back, so the pre-filter total was a second number restating what the
controls were already showing.

**That row cannot shift the grid, by construction rather than by mechanism.**
It used to hold a Clear link that appeared with the first filter and vanished
with the last, so it needed a reserved height to stop the grid dropping 23px at
the exact moment you clicked a pill. Clear is gone (see "deliberate decisions"),
and the two things left — the count and the sort — are both permanent, so there
is nothing to reserve height for. The one remaining floor is `min-height:44px`
on `.fpill.fsort > button`, which is the sort's touch target and incidentally
sets the row's 44px height; it is not an anti-shift device. Measured after the
change, at 1440px and 390px: row height 44px filtered and unfiltered, and the
pills, the grid and the first card all move **0.00px** on apply and on clear.
Measure `offsetTop`, not `getBoundingClientRect().top` — see the Playwright note
below for why that distinction cost an afternoon.

**Filter pills and the sort share one control scale — but only within a
breakpoint. Desktop is 15px, phones are 13.5px, and that split is deliberate.**
The point of one scale is hierarchy against the count inside a given layout, and
the two layouts have no reason to agree. Phones briefly ran at 15px to match
desktop and it cost 22px of pill-row overflow (55px → 77px) for nothing anyone
could see, pushing Foster-to-adopt further out of reach. Reachability beats
cross-breakpoint tidiness. Within each breakpoint the sort stays subordinate on
weight (500 vs 600), colour (muted vs full contrast) and chrome (no border, no
fill) rather than on size. The sort must never fill with accent: filled means
"you have narrowed the list", and something is always sorting.

**Four filter pills do not fit a phone, and no styling change will make them.**
At 390px the row needs 412.7px against 358px available. It is one label's fault:
`Foster-to-adopt 15` is **158.1px**, wider than Breed (78.2) and Age (64.9)
together, and the whole 55px overflow is attributable to it — shortening it to
"Foster" makes all four fit with room to spare. So the row scrolls, and
`paintPillFade()` puts a fade at whichever edge still has pills behind it.

Three things about that fade are load-bearing:

- **It is a `mask-image` on the scroller, not a gradient overlaid on top.** A
  mask cannot intercept a touch, so the pills under it stay tappable and the row
  stays scrollable with no `pointer-events` juggling. It also fades to
  *transparent* rather than to a colour, so it is automatically right in both
  themes — and the theme here follows NYC sunrise/sunset, not the OS, so a
  gradient hardcoded to a light background would be wrong every night.
- **A mask paints on the element's own box, so it deletes anything a descendant
  draws outside that box.** An open filter menu is `position:fixed`, full-width
  and five times the height of the row, and the first version of this made every
  filter menu on mobile silently invisible — the menu was in the DOM, correctly
  sized, and simply not painted. `paintPillFade()` therefore withholds the fade
  classes entirely while `.fpill.open` exists. **Anything added to this row that
  escapes its box needs the same treatment**, and the failure mode is invisible
  rather than noisy, so check it by hand.
- **The classes are the only thing that turns the mask on**, so a browser with
  JS disabled gets no mask and therefore cannot hit the bug above. The cue also
  never appears on desktop, where the row doesn't overflow, because `pillSlack`
  is 0 there.

`scrollWidth`/`clientWidth` are only read on resize and at the end of
`applyView()` — the latter because `paintFilters()` rewrites Foster-to-adopt's
count, which changes the label's width. Scrolling itself reads only
`scrollLeft`.

**The count is 19px/700 at every width — one rule, no breakpoint.** Do not
"restore" it to the retired day heading's 23px: it was 23px on desktop, and the
step down is deliberate, because the count now shares a row with the 15px sort
across ~790px and at 23px the two ends read as unrelated. 19px is exactly what
that heading dropped to on phones, which is also why the responsive override was
deleted rather than kept at a matching value. Matching the sort at 15px was
rendered and rejected: this is the page's only statement of scale now the date
headings and the "of M" are both gone, and at control size it reads as metadata
rather than as a heading for the grid.

**`.fbar-meta`'s negative bottom margin is optical, not structural.** The row is
a fixed 44px and the count is centred in it, so dropping the type from 23px to
19px moved no boxes at all but left ~3px more air between the numeral and the
first card. `margin:14px 0 -19px` puts the ink back where it was — 24px below
the pills, 15px above the cards. If you retune this, measure from the numeral's
rect, not the row's: the row's own gap to the grid reads 3px and is meaningless
on its own.

**The mobile sort carries its full "Sort by:" label again.** It was briefly
stripped to the bare value because the row also held `126 of 224 dogs` and a
Clear link, leaving 20.5px of line at 390px; a border was added to keep it
looking like a control. With the short count, no Clear and 13.5px type there are
89.9px spare, so the label is back and the border is gone — the affordance is
fixed by naming the control rather than by drawing a box round it.

The old treatment survives below 340px only. Carrying the label costs 55px, and
the slack runs out around 328px: at 320px it leaves 11.9px, which is the 8px
flex gap and almost nothing else, so a four-digit roster would collide. **That
threshold was re-derived when phones went back to 13.5px** — it used to be
359px, measured against a 15px sort, and was far too cautious. It now rides the
grid's existing 339px breakpoint rather than inventing a nearby one, and 340px
keeps 39.9px of slack. If you change the count's type or the sort's, re-measure
it; the two rules are coupled and nothing will tell you when it stops holding.
In that block the label is clipped rather than `display:none`, so screen readers
still announce "Sort by: Recently added" instead of a bare "Recently added",
which would say nothing about what the control does.

**Badges are mostly off, on purpose.** `SHOW_WAIT_BADGE_ON_CARDS = False` keeps
the ⏳ "listed N days" badge off grid cards (it hit 104 of 223 cards, 86 of them
one rescue) while leaving it on the dog page and modal. `NEW_MARK_MAX_SHARE =
0.5` suppresses the NEW marker entirely when more than half the grid arrived
today. See "things that will break" — the second one looks like breakage.

**Placement programs:** a dog can carry `program` / `program_label` /
`program_note`, meaning it's placed some way other than a straight adoption. It
drives an amber pill on the card, a chip in the modal, and the note above the
apply button. Korean K9's foster-to-adopt is the only one: 15 of their 29 dogs
are still in South Korea, met for the first time at pickup and taken home on a
7-day trial, so their button goes to `/foster-to-adopt/` instead of the standard
application. `KoreanK9Source.route` reads Petstablished's `current_location`,
which costs a detail request per dog — the field isn't in the listing payload.
The test is an **exact string equality against one constant**, `FOSTER_FIRST =
"5: Foster First"`; `"2: East Coast Dogs"` isn't matched by anything, it just
falls through to the standard track along with every other non-blank value.
Records with a blank location are on neither of their public pages and are
dropped; there were 2, one a stale duplicate of a dog already listed.

**Gone:** the Petfinder API, decommissioned 2 December 2025. It previously
carried Korean K9 and a city-wide fallback; Korean K9 now comes from
Petstablished and there is no city-wide fallback, so every rescue is explicit
in `sources/registry.py`.

**Crawlable pages:** `/`, `/rescues`, `/rescue/<slug>` and
`/dog/<rescue>/<slug>`, all listed in `sitemap.xml`. Flask maps the
extensionless URL to the `.html` file (`static_files` in `app.py`), so any new
static page must be reachable that way. Rescue pages were previously linked
only from individual dog pages; the homepage footer and the coverage FAQ now
link all of them. Outbound links to rescues' own sites are deliberately on
`/rescues` and the rescue pages only, never site-wide.

**Not verified:** the Docker image has never been built — no Docker on the dev
machine. Expect the first `docker compose up --build` to be where any
dependency issue surfaces. The app itself is smoke-tested (all endpoints 200 on
a fresh DB).

## Checking layout claims in a real browser

**Playwright is installed in `.venv` and deliberately not in
`requirements.txt`.** It is a development tool for verifying the built page; the
site neither imports it nor needs it, and pinning it into the deploy would put a
browser driver on the production image for nothing. Install it when you need it:

```bash
.venv/bin/pip install playwright   # the browser comes from channel='chrome'
```

Two reasons it's worth the trouble over clicking around by hand. The editor's
own browser tooling was unusable for this work — it kept reporting "No browser
tab available" — so driving local Chrome directly was the only reliable route.
More importantly, the claims this page makes about itself are numeric: "the grid
does not move when you filter" is either 0.00px or it isn't, and "the sort has a
44px touch target" is a measurement. Eyeballing a screenshot cannot settle
either, and both were wrong at some point during the layout work.

**One trap, because it produced a convincing false positive.** Measuring card
positions with `getBoundingClientRect().top` reported every card 6px higher
after a click. There was no layout shift: `.card:hover` applies
`transform: translateY(-6px)`, the automated click left the pointer sitting on
the card it had just clicked, and `getBoundingClientRect` includes transforms.
So measure `offsetTop`, which is the layout box and ignores transforms, and move
the pointer somewhere harmless (`page.mouse.move(2, 2)`) before every
measurement. Any future check of this row should do both.

## Things that will break, and why

1. **HTML scrapers break when rescues redesign.** Three of seven parse HTML.
   Each is isolated in a try/except, logs, and emails `ALERT_EMAIL`; the page
   still builds from whatever worked. A source returning **0 dogs** also
   alerts — that's usually a broken selector, not an empty shelter.
2. **Rescue contact methods change.** `rescue_contacts.json` encodes whether
   each rescue takes email or requires an application first. 5 of 7 require an
   application — sending people to email would get them bounced. Re-verify
   occasionally.
3. **The ratings are estimates.** Derived from the rescue's write-up plus breed
   tendencies, and labelled as such in the UI. Don't let anyone present them as
   assessments of an individual animal.
4. **`/img` is an allowlisted proxy.** It exists so the share canvas can export
   cross-origin photos. Adding a source means adding its photo host to
   `_IMG_HOSTS` in `app.py`. Do not make it open — that's an SSRF hole.
5. **A Flask process without outbound network makes share cards fail and looks
   like a code bug.** This one cost a day already, so read it before you debug
   anything about share cards.

   The share-card composer draws every photo through `/img` rather than loading
   it directly, because a cross-origin image taints the canvas and `toBlob()`
   then throws. So the *server* fetches the photo. If that server was started
   somewhere without outbound access — a restricted sandbox, a locked-down CI
   container, a box with no egress — `/img` returns **502 for every photo** and
   each share card silently falls back to its placeholder.

   What makes it deceptive is the asymmetry: **the grid thumbnails still look
   perfectly fine**, because the browser loads those straight from the rescues'
   own hosts and never touches Flask. So the page looks healthy, one feature is
   broken, and nothing in the UI points at the network.

   Diagnosis is one line:

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' \
     'http://127.0.0.1:8000/img?u=https://g.petango.com/photos/606/c0cc0979-6231-4a00-bbea-531855b17448.jpg'
   ```

   200 means the proxy is fine and the bug is real. 502 means restart the server
   with network access and try again. The server log says the same thing —
   `/img upstream failed for <url>: ...` with a `ProxyError` or `ConnectionError`
   behind it. Note 403 is a *different* fault: that's a photo host missing from
   `_IMG_HOSTS`, and the log names the refused host.

   Recent hardening, so the next person gets told rather than guessing: photo
   loads time out after 8 seconds (`loadImg`) so a hung proxy can't strand the
   modal on "Building…" forever, every failure is named in a `console.warn`
   giving the exact `/img` URL, and a card that failed to load a photo now says
   **"Photo wouldn't load"** instead of "Photo coming soon". The old wording was
   the actual trap: it claimed the rescue hadn't photographed the dog, which is
   a real and common situation, so the failure impersonated normal data.
6. **Korean K9's location codes are free text they control.** The match is exact
   string equality on `"5: Foster First"`, so a rename — or an added space, or a
   change of case — quietly turns those 15 dogs into normal adoptions and we'd
   send people to the wrong application. `route` keeps unknown codes rather than
   dropping them, so the failure is a wrong label, never a missing dog.

   **A run now warns rather than waiting to be noticed.** If Korean K9 returns
   dogs and *not one* of them matches `FOSTER_FIRST`, `_check_foster_split()`
   prints a line in the same shape as the other scraper warnings:

   ```
   WARN  koreank9       no dog matched '5: Foster First' — check whether their
                        location code changed. Saw: '2: East Coast Dogs', '5: Foster first'
   ```

   The list is every distinct non-blank location string that run saw, which is
   the thing you need: a renamed code is usually sitting right there in it, one
   character off. **What to do:** open their two public pages, find the code
   they're using now, and update `FOSTER_FIRST` in
   `sources/rescues/koreank9.py`. Do not "fix" it by loosening the match to a
   substring or a case-insensitive compare unless you've checked what else that
   would catch — mislabelling a standard adoption as foster-to-adopt sends
   people to the wrong application just as badly in the other direction.

   It warns and continues; it never raises and never drops a dog. It can't fire
   on an unrelated failure either — a fetch that throws never reaches the check,
   and a fetch that returns nothing returns early, because "returned 0 dogs" is
   already alerted on by rule 1 and a second warning would only bury the first.

   It will also fire, correctly and unavoidably, on the day Korean K9 genuinely
   places every foster-track dog. That state is indistinguishable from a rename
   from where we stand, which is why the message asks a question instead of
   declaring a fault. The code list tells the two apart: a string that is nearly
   the constant — different case, a stray space, a renumbering — is a rename,
   and a list of plainly unrelated locations means they just have none today.
7. **A fresh database renders no NEW markers at all**, and it looks broken. Every
   dog is seen for the first time today, so today's arrivals are 100% of the grid,
   so `NEW_MARK_MAX_SHARE = 0.5` suppresses the marker everywhere. This is the
   flag doing its job — a marker on all 230 cards marks nothing. Markers come
   back on the first day the roster is a mix. Before debugging the renderer,
   check whether every dog's `first_seen` is today.
8. **Most of "Longest waiting" depends on scrapers that could stop supplying a
   date.** `listed_since` is now parsed per source through `sources/dates.py`
   (Petstablished `created_at` for Korean K9, NYC Second Chance and Waggytail;
   the WordPress post date for Sugar Mutts; "Brought to the shelter" for Sean
   Casey). Animal Haven and Muddy Paws expose no date at all, so their dogs fall
   back to `first_seen` and sort as the shortest waits. 154 of 230 have a real
   date today. If that number collapses, the sort goes quietly inert again rather
   than erroring — which is exactly how it went unnoticed the first time, when
   Petfinder's removal left it the only populator and every `waiting_days` was 0.

   **`listed_since` is never persisted.** Unlike `first_seen`, it isn't in the
   `seen_dogs` table or anywhere else in SQLite — it's re-read from each rescue's
   feed on every run and only exists baked into the built HTML. So there is no
   stored history to cushion a scraper that stops supplying the field: the day a
   rescue drops or renames its date, every one of its dogs silently falls back to
   `first_seen` and the wait it had been showing is gone, not stale. Nothing
   alerts on this, because an empty date is a legitimate state for the two
   rescues that never had one.

## Deliberate decisions worth not undoing

- **Photoless dogs are shown**, sorted last. They're currently 9 puppies whose
  litters arrived before the camera did. Hiding them would bury the newest
  arrivals and make the count untrue.
- **View counts are real.** No seeding, no inflation. Hidden below 1 view.
- **One NYC clock.** SQLite's `datetime('now')` is UTC; after 8pm Eastern that
  rolls the date and the evening's arrivals stop counting as new. Everything
  dates off `America/New_York`.
- **Dogs are never deleted from the page when they gain a photo or change** —
  only when the rescue stops listing them, which means adopted.
- **A program's terms sit above the apply button, not in the bio.** Korean K9's
  foster-to-adopt dogs are a 7-day trial on a dog flying in from South Korea. The
  chip alone would read as a feature; the sentence next to the button is what
  stops someone applying for a dog they think they can go meet this weekend.
- **Within one source, only an identical name *and* cover photo counts as a
  duplicate** (`Dog.reprint_key`). Name-and-breed matching is safe across
  rescues but not inside one, where two dogs can share a name and many have
  breed "Unknown".
- **No behaviour filters — good with kids/dogs/cats, house-trained.** Only 3–14%
  of listings fill those fields in and coverage varies by rescue, so the results
  would describe how thoroughly each rescue types its records rather than which
  dogs exist. Filtering on an absent field also misrepresents the dog: blank is
  not "no". Two clicks would land on a confident, false zero. Petfinder's filter
  sprawl is the anti-goal. Four pills of facts the rescues actually record is the
  whole intended surface.
- **Filter option counts are computed against the other active filters but not
  their own pill.** That's what makes every number in an open menu reachable and
  guarantees you cannot click your way to an empty grid. The age buckets carry a
  matching invariant: every dog is in exactly one of Puppy/Young/Adult/Senior/
  **Unknown**, so the options sum to the total and "Any age" is never bigger than
  its parts. Don't drop the Unknown bucket to tidy the menu — that strands every
  dog with an unreadable age in a list nothing can reach.
- **The two sort options key on different fields, and that is not a bug.**
  "Recently added" is `first_seen` (when LUVD saw the dog); "Longest waiting" is
  `waiting_days`, which prefers the rescue's own `listed_since`. Pointing both at
  one field would let a dog we noticed yesterday sort as brand new while its own
  badge reads "⏳ 300 days" — a contradiction visible in a single glance.
- **Saving and unsaving behave differently in the two views, deliberately.** In
  the saved view the grid *is* the saved list, so unsaving removes the card and
  clearing the last one reveals the empty state. In the main grid a heart tap
  changes only the heart — the card you just tapped must never move or vanish
  under your finger. One line does it: the heart handler calls `applyView()` only
  `if (showingSaved)`. Removing that guard breaks the saved view; making it
  unconditional breaks the main grid.
- **Entering the saved view clears active filters; leaving puts them back.** The
  asymmetry is the point, and it's easy to mistake for a bug from either side.
  Entry clears because a saved list is a handful of dogs and leaving pills
  applied behind a filter bar we've just hidden would silently shorten it with
  no visible cause — you'd see four of your six saved dogs and nothing on screen
  would say why. Exit restores because the filters were a search you were in the
  middle of, and checking a saved dog shouldn't cost you it. `toggleSavedView()`
  stashes `FILTERS` and `fosterOnly` on the way in and reapplies them on the way
  out; `stashedFilters` is null whenever we're outside the saved view. The sort
  order persists throughout — it was never cleared.
- **The count row has no Clear button, and the page has no bulk reset except in
  the zero-results state.** Clear used to sit beside the count and read as a
  hyperlink stapled to a heading. Nothing became unreachable when it went: every
  pill menu's first row is "Any breed"/"Any gender"/"Any age", and
  Foster-to-adopt is a toggle, so each filter can be undone where it was set.
  The one exception is `#fe-clear` ("Show all dogs") inside `#filter-empty`,
  kept because zero results is the only genuine dead end — the grid is empty, so
  there's nothing on screen to suggest which pill to undo.

  Worth knowing before you decide `#fe-clear` is dead code: **you currently
  cannot click your way to zero results**, because menu options that would yield
  nothing are disabled (see the filter-counts entry above). Measured on the
  current roster, the smallest count on any enabled option in any menu is 1. So
  `#filter-empty` is a safety net for a state the UI prevents, not a screen
  users reach. It becomes reachable the moment anything sets `FILTERS` without
  going through a menu, which is exactly when you'd want it.
