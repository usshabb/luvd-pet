# LUVD NYC — handoff

A daily-updating page of every adoptable dog across NYC rescues.
Python + Flask + SQLite, containerised. `DEPLOY.md` is the step-by-step.

## Deploying

**Production deploys on push.** `.github/workflows/fly-deploy.yml` runs
`flyctl deploy --remote-only` for every push to `main` — no tests, no staging,
no approval step. Treat `main` as the release branch and read `DEPLOY.md`'s first
section before pushing; the two things that catch people out are that migrations
run at container boot rather than in CI, and that a second push cancels a deploy
still in flight.

The manual VPS path still exists, for a box you own rather than Fly:

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
| `app.py` | Serves the page + `/subscribe`, `/unsubscribe`, `/view`, `/img`, `/sitemap.xml`. |
| `emailer.py` | Every outbound message, and the only place that knows Mandrill. |
| `og_image.py` | Rebuilds the 1200×630 social card nightly. |
| `montage.py` | Rebuilds the welcome email's four-polaroid montage nightly. |
| `imaging.py` | The Pillow helpers those two share — font, fetch, crop-to-fill. |
| `sheet_sync.py` | Mirrors the `subscribers` table to a Google Sheet as an offsite backup. Never a store. |
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

`subscribers` is the one table with a second copy: `sheet_sync.py` mirrors it to
a Google Sheet on every signup, every unsubscribe, and again at the end of the
nightly run. That covers the list, and only the list — `first_seen` and
`dog_views` still live nowhere but the volume, so the tarball above is still the
backup that matters.

## Environment

Copy `.env.example` → `.env`. Required to be fully live:

| Var | Effect if missing |
|---|---|
| `LUVD_DOMAIN` | Caddy won't start |
| `SITE_URL` | Emails and OG tags point at localhost |
| `MANDRILL_API_KEY` | **No email sends at all** (signups still captured) |
| `ALERT_EMAIL` | Scraper failures are silent |
| `ANTHROPIC_API_KEY` | Optional — upgrades breed-guide text |
| `SHEET_WEBHOOK_URL` | Optional — no subscriber sheet mirror; SQLite is unaffected. Set it as a Fly secret, not in `.env`: the URL is the credential |

## Adding keys after launch

Mandrill is optional at deploy time and can be added any day after. No rebuild —
`env_file` is read when the container starts:

```bash
nano /opt/luvd/.env          # add the key(s)
docker compose up -d         # recreates containers with the new env
docker compose run --rm cron python check.py   # optional: apply immediately
```

**Until Mandrill is added:** signups are still captured to the database — they
just don't receive anything yet. Whoever subscribes on day one gets their first
email the morning after the key lands. Nothing is lost. Unsubscribes still work
and still take effect immediately; they just go out quietly. Scraper failure
alerts are also silent until then.

Verified: a full nightly run with **no keys at all** exits 0, builds the page
and the share card, and only logs that email couldn't send. No key is needed to
fetch dogs — every rescue source is a public endpoint.

## The three emails

All three live in `emailer.py` and share one header, one card and one grid.

| Email | Trigger | Sender |
|---|---|---|
| Welcome — "You're on the list" | `POST /subscribe`, only when `db.add_subscriber()` says the address wasn't already active | `send_welcome()` |
| New dogs — "N new dogs in NYC today" | the 05:30 run, only when dogs nobody has been shown turn up | `send_digest()`, from `check.py` |
| Goodbye — "Sorry to see you go" | `GET` or one-click `POST /unsubscribe`, only when `db.deactivate_subscriber()` says this call is the one that took them off | `send_goodbye()` |

**Both one-offs go out on a daemon thread** (`_mail_in_background()` in
`app.py`). `send_email()` allows itself 30 seconds and there are two gunicorn
workers, so a synchronous send on a form post would be enough to stall the
site. Every failure — no key, Mandrill down, a rejected address, the thread
refusing to start — is logged and dropped. That matters most on the
unsubscribe: leaving is a compliance promise and cannot be made to wait on an
email provider, so the row is already committed and the confirmation already
owed before any of this runs.

**Exactly one goodbye, and the claim is the write.** `deactivate_subscriber()`
returns whether its `UPDATE ... WHERE email = ? AND active = 1` changed a row,
the same shape `add_subscriber()` uses. Two clicks on the same link, or a mail
client firing the one-click endpoint after the reader already used the footer
link, can only produce one changed row and so one email. A read-then-write
would leave a window between the check and the update that both could pass
through. The `unsubscribed` column added alongside it is a record of when they
left, not the lock — it could be dropped and the guarantee would still hold.

**The welcome's montage is a pre-rendered image, and the email checks it
exists before naming it.** `montage.py` composites four dog photos into
`public/welcome-montage.jpg` — 1000×392, ~73KB, tilted polaroid frames with
each dog's name in the bottom edge — and `check.py` rebuilds it every night
beside the share card, from dogs currently listed, so somebody subscribing
today sees dogs actually waiting. Like the share card it is **never fatal**: a
failure leaves last night's file in place and the run carries on.

*Why an image and not HTML:* email cannot rotate an element or lay text over a
photo with any reliability — Outlook drops CSS transforms outright — so an HTML
version would collapse into the stacked photo-and-caption grid the digest
already has. One flat file renders identically everywhere.

*Why four:* the email displays it at 504px, so each photo lands at about 129px,
and about 77px on a 300px-wide phone card. Five in one row takes that to 60px.
Two rows of smaller cards was the first attempt and it was worse: the lower row
sits on the upper row's captions, and clearing them makes the image 740px tall.

*Why the existence check:* the file is gitignored, like `og.png`, so a box that
has deployed but not yet run `check.py` has no montage. `emailer._montage()`
returns an empty string unless the file is really on disk — an `<img>` pointing
at a 404 is worse than a mail with no picture in it, and the no-montage welcome
is a tight, deliberate-looking three blocks. Same bargain the goodbye makes
with an unreadable roster.

*Why `?v=<mtime date>` on a stable filename:* Gmail and Outlook.com proxy and
cache remote images by URL, so a fixed name whose contents change nightly would
serve subscribers a montage from weeks ago. Dating the filename would beat the
cache too, but leaves ~73KB per day on the volume forever and makes the email
go looking for the current one. The query is derived from the file's own mtime,
not today's date, so if a run fails the tag stays put and the proxy keeps
serving the copy it already has — which is the right answer. `page.py` already
busts `og.png` this way.

*Shared code:* `imaging.py` holds the three helpers both compositors need —
font loading with an on-disk fallback list, photo fetch, crop-to-fill. They
were `og_image.py`'s private functions; they moved rather than having
`montage.py` import from a module named for a different output.

**The goodbye is the only email that reads the roster at send time.** The web
process never scrapes, so `roster()` pulls the dog payload out of
`public/index.html`, the same JSON the site renders from and the only thing on
disk that knows photo URLs. Every failure returns an empty list and the mail
goes out with no grid: missing file, no `const DOGS`, malformed JSON, empty
roster, nothing photographed. The digest can assume dogs exist because it only
runs when there are new ones; this one runs whenever somebody leaves, which may
be the morning the page is half-written. Three faces and two, not six and four
— fewer than the digest so it reads as a wave rather than one last pitch, and
the largest counts that fill a single complete row in each layout instead of
ending on an orphan tile.

**The phone grid is the base layout and the desktop grid is the enhancement.**
That is the reverse of the obvious way round, and it is deliberate: the widest
grid is the one that can overflow, so it must be the one behind the media
query, not the one every client falls back to. `.g-phone` renders by default;
`.g-desk` carries `display:none;mso-hide:all` and is revealed by
`@media (min-width:601px)`. Two clients never apply that query — Outlook on
Windows, which ignores media queries, and the Gmail app signed into a non-Gmail
account, which strips the `<style>` element outright. Both used to get the
three-across grid, which measures 548px of content inside a 390px screen, so
the third column was cut off. Both now get two-across, which fits. **The cost,
accepted:** Outlook on Windows shows the phone layout on a wide screen — four
dogs two across in a 560px card. Sparse, not broken. The `mso-hide:all` and the
Outlook `object-fit` fallback both belong on whichever table Outlook actually
sees, so they moved with the inversion: the fallback is on the phone tiles now,
and the phone table must never carry `mso-hide:all` or Outlook shows no grid at
all. `+ N more on the site` inverted with it — the phone count is the base.

**Two across never ends on a lone tile.** `build_html()` drops the last dog
from the phone selection when it would be odd, so three new dogs show two and
say "+ 1 more on the site" rather than stranding the third on its own row,
where it reads as an image that failed. Three new dogs in a day is common, so
this fires often. One dog is exempt: that is a single row, not an orphaned one.
Desktop has its own version of the rule in `_grid()` — four dogs go 2×2 rather
than three-then-one — and is otherwise untouched.

**No `List-Unsubscribe` headers and no unsubscribe link on the goodbye.** Both
of the other two carry them, because Gmail and Yahoo require them of bulk
senders. Offering one more to somebody who has just unsubscribed suggests it
didn't take.

**The emails load their own copy of the logo.** `emailer.LOGO_FILE` points at
`/assets/luvd-logo-email.png` — 300×130 and 3,836 bytes, against the site
logo's 1400×607 and 274,990, which is **271KB off every single send**. It is
displayed in a 150×65 box, so 300 is exactly 2× for a retina screen. 150×65 is
30:13, the source ratio to within 0.05%, which is why both numbers are whole:
change the display size and the asset has to be regenerated at twice it, or the
mark goes soft.

**It has to ship in the same deploy as the code that names it.** The file lives
in `public/assets/`, which is tracked, so a normal commit carries both and
there is no window where deployed code asks for a file the domain doesn't have.
Until that deploy lands, `https://luvd.com/assets/luvd-logo-email.png` returns
404 — so **a sample send from a developer machine has to override `LOGO_FILE`
to `/assets/luvd-logo.png` first**, and every image URL in the message should
be fetched for a real 200 before it goes out. Sending one with a missing logo
is exactly the mistake this paragraph exists to prevent.

Regenerating it: premultiply the alpha before resampling (`convert('RGBa')` →
resize → `convert('RGBA')`), because the source stores near-black RGB under its
transparent pixels and a straight RGBA resize averages that into the edges. The
white sticker keyline is what keeps the red wordmark visible on a dark
background, so check it against black as well as white. Then **save it as a
palette PNG** — `quantize(colors=64, method=FASTOCTREE)` and save the `P`-mode
image directly. A wordmark is two flat colours and some antialiasing, so 64
colours costs a worst-case 15/255 on one edge pixel and takes the file from
19,687 bytes to 3,836. Quantising and converting back to `RGBA` before saving
throws the whole win away. `luvd-logo.png` is what the site itself uses and
must not be touched.

**The footers are the wordmark and, on the two bulk mails, an unsubscribe link
— nothing else.** The digest's date and "you only get this when there are new
dogs", the welcome's "you're getting this because you signed up at luvd.com"
and the goodbye's "sent because … unsubscribed at luvd.com" were all removed at
the owner's request; `_footer()` is the one place they lived. Two consequences
worth knowing: the grey is `#6e6e73` rather than the `#98989d` these lines used
to be, because #98989d on white is 2.5:1 and fails WCAG AA where #6e6e73 is
5.1:1 — and, more seriously, **with no reason-for-receipt line and no postal
address these mails no longer carry the sender identification CAN-SPAM expects
of commercial bulk mail.** The `List-Unsubscribe` headers are still there and
still required, but they are not the same thing. This was a deliberate call
about how the mail should read, recorded here rather than lost.

**The goodbye's photos have no captions; the digest's do.** In the digest
somebody is choosing which dog to open, so the name and rescue are the point.
In the goodbye nobody is choosing and the faces are decoration, so `_tile()` is
called with `caption=False`, which also drops the cell's bottom padding from
14px to the 9px gutter so the grid doesn't float above a gap where text used to
be. The name still rides in the img `alt`, so a blocked-image render and a
screen reader both keep it, and the plain-text goodbye still lists names and
links because there are no photos there to carry them.

## Known state

**Working:** 7 scrapers, 230 dogs. Muddy Paws (JSON API), Animal Haven (HTML +
detail pages), Waggytail (Petstablished API), Sugar Mutts (HTML), Sean Casey
(HTML), Korean K9 (Petstablished org `1956188`, routed by location — see below),
NYC Second Chance (Petstablished org `83716`, with per-dog trait flags). The dog
count moves daily; a run's own output is the only current one.

**The page is one flat grid.** The per-day sections and their date headings are
gone — they didn't survive filters, which scattered a few matches across a dozen
headings each announcing "1 dog". Above the grid: four filter pills (Breed,
Gender, Age, Foster) on their own centred row, then a results header
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

**The two rows are on two different scales, and that is the hierarchy.** The
filter pills are the control scale — 15px on desktop, 13.5px on phones. The count
is the heading — 19px desktop, 17px phones. The sort is **17px at every width**:
it sits on the count's line but it is a control, so it lands between the two
scales and steps with neither. The desktop/phone split on the other two is
deliberate: the point of one scale is hierarchy inside a given layout, and the two
layouts have no reason to agree. Phones briefly ran the pills at 15px to match
desktop and it cost 22px of pill-row overflow for nothing anyone could see.

**The sort trigger reads "Sort by" and never shows its value.** Not in either
state — picking "Longest waiting" does not change the visible label. This was
first built as a conditional (name the control on the default, name the value
once you've changed it) and that was rejected on sight: a label that changes
shape is its own kind of confusing, and with two options, one of them the
default, the value is worth little and costs the widest string in the row. The
selection is marked inside the menu instead, in the accent colour the filter
menus already use. **`paintSort()` therefore owns the `aria-label`, which always
carries the value** (`"Sort by: Longest waiting"`), and that is now the only
thing carrying the answer for anyone who can't open the menu and look — do not
let it become conditional. The sort must also never fill with accent: filled
means "you have narrowed the list", and something is always sorting.

**All four filter pills now fit a 390px phone, with 0px of overflow.** They
didn't until the pill label was shortened. `Foster-to-adopt 15` measured
**158.1px**, wider than Breed (78.2) and Age (64.9) together, and the entire
55px overflow was attributable to that one string; the pill now reads `Foster`
and the row fits. See "deliberate decisions" for the trade that came with it.

**Do not treat `paintPillFade()` as dead code now that 390px fits.** The row
still overflows by 61px at 320px, and the fade is keyed on measured overflow
rather than on a breakpoint, so it shows itself exactly where it's needed and
stays away at 390px on its own. It is also the thing that will tell you if a
future label pushes the row back over.

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
`applyView()` — the latter because `paintFilters()` rewrites Foster's count,
which changes the label's width. Scrolling itself reads only `scrollLeft`.

**The count is 19px/700 on desktop and 17px/700 on phones.** Do not "restore" it
to the retired day heading's 23px: the step down is deliberate, because at 23px
the two ends of that row read as unrelated things sharing a line. Shrinking the
*count* to the 15px control size was rendered and rejected too — it is the page's
only statement of scale now the date headings and the "of M" are both gone, and at
control size it reads as metadata rather than as a heading for the grid.

**19 to 17 is the count moving with the type ladder, not an exception to it.**
Everything steps across this breakpoint — card names 23 to 19, pills 15 to 13.5 —
and the count had to, because 19px is exactly `h3.nm`'s phone size: at 19px the
count was the same size *and* weight as the cards it heads, and measured at 390px
it read as one of the names rather than as a heading over them. Desktop stays 19px,
where `.nm` is 23px. Only the size moves — the `<b>` carries no size of its own so
the numeral comes with it, and the bold, the tracking and the left flush are
unchanged.

**The sort is 17px at every width and is deliberately NOT tied to the count.** It
was 19px for a while, matched to the count on the theory that the two ends of the
results header should agree on size. Rejected: that made the least-used control on
the page the loudest thing in its own row, and louder than the four filter pills
above it. It is a control, not a heading, so it takes one value at both
breakpoints — expressed as a single base declaration with no mobile override, and
the `max-width:680px` block is where the *count* comes down to meet it. 17px still
clears the pills' control scale, so it stays legible as part of the results header
rather than reading as a fifth filter.

**The sort button's `line-height:1.2` is load-bearing, not cosmetic.** At the
body's 1.47 a 19px label measures 27.9px, which with padding and border comes to
45.9px — over the `min-height:44px` floor, so the type rather than the floor
starts setting the height and the whole results row silently grows 2px. 1.2 puts
the content at 40.8px and leaves the floor in charge with ~3px of headroom. At
today's 17px there is more headroom still, so the floor governs comfortably —
measured 44.00px at 1440px, 390px and 320px, filtered and unfiltered.
Nothing is clipped; the button centres its label in the full 44. **If you change
the sort's type size, re-measure the row**, because that floor is what the row's
44px and the negative margin below are both derived from.

**`.fbar-meta`'s negative bottom margin is optical, not structural.** The row is
a fixed 44px and the count is centred in it, so dropping the type from 23px to
19px moved no boxes at all but left ~3px more air between the numeral and the
first card. `margin:14px 0 -19px` puts the ink back where it was — 24px below
the pills, 15px above the cards. If you retune this, measure from the numeral's
rect, not the row's: the row's own gap to the grid reads 3px and is meaningless
on its own.

**The narrow-phone `@media (max-width:339px)` block is down to one rule.** It
used to strip the sort back to its bare value behind a border, because
`Sort by: Recently added` ran the results row out of line below about 340px.
With the trigger down to `Sort by` that whole problem is gone: at 320px the
count and the sort leave **123px** of slack. The block now does nothing but drop
the grid to a single column, and the fallback was deleted rather than left in
the file being read as still-needed.

**The menu chevrons are drawn SVGs, not the character `▾`.** One `CHEVRON`
constant in `page.py` feeds all six — the two headline pickers, the three filter
pills and the sort. The glyph was replaced for two reasons: it is small for its
font size and differently proportioned in every platform font, and being *text*
it sat inside each button's accessible name, so the sort announced as
`"Sort by: Recently added ▾"` and a screen reader could read the triangle out.
Sizing is `.72em`, which keeps the pills' chevrons in proportion across both
breakpoints from one declaration: 10.80px at 15px, 9.72px at 13.5px. The three
hardcoded pixel sizes that preceded it had already drifted to 9px on the pills
against 13px on the sort. The headline pickers take their own `.24em`, since
`.72em` of a 56px headline would be a 27px chevron.

**The sort's chevron takes its own `.66em`, and that is not a rounding of
`.72em`.** It draws 11.22px at both widths, a real step down from the 13.68px it
drew at the old 19px and only a hair above the pills' 10.80px. Two reasons it is
not on the shared ratio. The arrow is the least informative mark in the row — it
says "this opens", which the control already says — so it is the first thing that
should give up size when the row is crowded. And a ratio of its own means the
arrow does not swing every time the sort's type is retuned: `.72em` of 17px would
be 12.24px, which is scaling with the label rather than deciding a size. Do not
"simplify" this back onto `.cv`.

**That change cost 15.7px of phone pill row and it had to be paid back.** A
drawn chevron is ~5px wider than the glyph's advance width, across three pills,
which re-broke the 390px fit the `Foster` rename had just bought (7px of
overflow). The 2px of side padding taken off `.fpill > button,.fpill-t` on
mobile (14px → 12px) returns 16px across four pills. **If you touch either the
chevron ratio or that padding, re-measure the row at 390px** — these two are
now holding it at exactly 0px of overflow.

**Badges are mostly off, on purpose.** `SHOW_WAIT_BADGE_ON_CARDS = False` keeps
the ⏳ "listed N days" badge off grid cards (it hit 104 of 223 cards, 86 of them
one rescue) while leaving it on the dog page and modal. `NEW_MARK_MAX_SHARE =
0.5` suppresses the NEW marker entirely when more than half the grid arrived
today. See "things that will break" — the second one looks like breakage.

**The NEW marker says "New here", from `NEW_MARK_LABEL` in `page.py`.** One
constant, because the runners-up ("Just in", "New face") are live options and
the string would otherwise get copied. It renders uppercase via
`text-transform`, so the constant is title case and the badge reads NEW HERE.
Measured at 1440px, 390px and 320px: it does not wrap, stays inside the photo,
and clears both the heart (top-right) and the 🔥 view chip (top-left) — it is
bottom-right, in the corner the wait badge vacated. It is 39% of the card width
at 390px, which is the tightest case; a materially longer string would not fit.

**On desktop hover, the badge hides rather than sharing the card with the quip
bubble.** The bubble is wider than the badge but not wide enough to cover it, so
the badge's red ends showed on either side of the white and read as a rendering
fault. It is hidden, not nudged: quips are per-dog strings of different lengths
and some wrap to two or three lines, so any geometry tuned to today's longest
quip stops clearing it the next time the bubble grows or the card narrows.
Verified against the longest quip on a badge-carrying card, not an average one.
The rule lives **inside `@media (hover:hover) and (pointer:fine)`** with the
bubble itself — on a phone there is no bubble, so there is nothing to hide
behind and the badge must stay put. Verified on a touch-emulated viewport: badge
at full opacity, bubble `display:none`.

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

## Grouping today's arrivals was built, and rejected

Worth writing down, because the live site still shows the thing that prompted it
and it will look like an obvious improvement again.

luvd.com groups new arrivals by day, and that reads well there. Looked at
properly, it has exactly **two** sections — "July 29th · 10 dogs" above "July
27th · 78 dogs". There is no daily rhythm; it is one small new group above a
pile holding 89% of the list. So the middle path was tried: keep the flat grid,
give today's arrivals their own lead group, label the remainder, two groups
only, behind a `SHOW_NEW_TODAY_GROUP` flag. It was built, it worked, and it was
removed the same morning after being seen.

Three reasons it isn't coming back:

- **It didn't earn its space.** A "NEW TODAY · 8 dogs" heading plus an "Already
  here · 222 dogs" heading, directly under a count line already reading "230
  dogs", is three stacked headings before you reach a single dog. The per-card
  badge says the same thing where it's actually useful — on the dog.
- **Headings lie under filters.** Each heading has to state its own filtered
  count, and a heading whose group filters down to nothing must not render. That
  is exactly what killed per-day sections. Two groups make it tractable, not
  free: the implementation had to withhold *both* headings whenever either group
  emptied, or you get a lone heading captioning the whole grid.
- **It contradicts the other sort.** Grouping by arrival date while ordering by
  wait length is self-contradictory, so grouping had to disappear entirely under
  "Longest waiting" — a whole second layout to maintain for one control.

It also forced the per-card NEW badge to stand down while a heading was showing,
which meant two mutually exclusive ways of saying "new" and a flag to choose
between them. The flag was deleted rather than left switched off; the code is in
git history if anyone revisits.

**Per-day sections are a separate, older rejection** and that one is firmer: in
production the page accumulates a section a day and only sheds one when a rescue
delists a dog, so within weeks a narrow filter scatters a handful of matches
across a dozen headings each announcing "1 dog".

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
- **Signup and unsubscribe have two independent side effects, and both go
  through `app.py`'s one `_in_background()` helper.** The transactional email
  and the subscriber sheet mirror are separate features that happen to hang off
  the same two endpoints. They share the helper on purpose: each needs the same
  two guarantees, and writing them twice is how one eventually loses one. The
  invariants, in order of how much they cost to break:
  - **Neither may run on the request thread.** `send_email()` allows itself 30
    seconds and `sheet_sync` 30 more, against two gunicorn workers. A form post
    that waits on either can stall the site.
  - **Neither may fail the request, and neither may suppress the other.** The
    database write is committed before either starts, so every failure past
    that point is logged and dropped. This matters most on unsubscribe: leaving
    is a compliance promise and cannot be made to wait on, or fail because of,
    a third-party API.
  - **Both are gated on the database write's return value, not on the
    request.** `add_subscriber()` returns whether a welcome is owed and
    `deactivate_subscriber()` whether a row actually went inactive; both claim
    that in the write itself rather than a read-then-write, so two simultaneous
    posts can only produce one. That single test is what makes the welcome
    arrive exactly once *and* keeps the mirror from re-posting a table that
    didn't change.

  If you add a third side effect here, hang it off the same helper and the same
  return value. Do not inline it into the handler.
- **A program's terms sit above the apply button, not in the bio.** Korean K9's
  foster-to-adopt dogs are a 7-day trial on a dog flying in from South Korea. The
  chip alone would read as a feature; the sentence next to the button is what
  stops someone applying for a dog they think they can go meet this weekend.
- **The filter pill says "Foster"; everything else says "Foster-to-adopt".** The
  short label is only on the pill, and it is what let all four pills fit a
  390px phone — the long form measured 158.1px, wider than Breed and Age
  together, and was the entire cause of the row's 55px overflow. The card chip,
  the modal chip, the note above the apply button and the pill's own
  `aria-label` all keep the full program name; the pill's visible text is a
  hardcoded literal in `page.py`, wholly independent of each dog's
  `program_label`, which the scraper sets. **The residual risk, on the record:**
  "Foster" alone can be read as fostering temporarily, which is a materially
  different arrangement from fostering with intent to adopt. The card chip is
  the only thing preventing that misreading. If anyone ever removes the chip,
  the pill becomes misleading and must be renamed back.
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
