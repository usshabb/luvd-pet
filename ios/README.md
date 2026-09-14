# LUVD for iOS

A native SwiftUI app over the same data as luvd.com: every adoptable dog from
the rescues LUVD follows, searchable and filterable, with a swipe deck for
browsing and a push notification on mornings new dogs are listed.

No third-party dependencies. iOS 17+, iPhone.

## Run it

Open `LUVD.xcodeproj` in Xcode, pick an iPhone simulator, press Run.

From a terminal:

```bash
xcodebuild -project LUVD.xcodeproj -scheme LUVD -destination 'platform=iOS Simulator,name=iPhone 17' build
```

The app talks to `https://luvd.com` by default. To point a build at a local
server (`PORT=8010 .venv/bin/python app.py` from the repo root), pass a launch
argument — nothing is persisted:

```bash
xcrun simctl launch --terminate-running-process booted com.luvd.app -LUVDBaseURL http://localhost:8010
```

### Works before the API is deployed

The app prefers `GET /api/dogs`. A server that predates it answers 404, and the
app then reads the dogs out of the city page itself (`const DOGS = [...]` —
the payload the website renders from). So a build pointed at production shows
live dogs today; device registration quietly waits until `/api/devices` exists.

## Push notifications

### Try the tap-through without Apple

Debug builds have **Settings → Developer → Test alert** buttons. They fire a
local notification in 4 seconds, shaped exactly like the server's push. Lock
the simulator (⌘L), wait, tap it.

Or send the real server payload to the simulator. This reads dogs from a local
server (`PORT=8010 .venv/bin/python app.py`), because `/api/dogs` only exists on
luvd.com once this branch is deployed:

```bash
cd .. && .venv/bin/python - <<'PY' > /tmp/luvd.apns
import json, urllib.request, push
from sources.base import Dog
d = json.load(urllib.request.urlopen("http://localhost:8010/api/dogs?city=NYC"))["dogs"][:5]
p = push.build_payload([Dog(id=x["id"], name=x["name"], source="", source_label=x.get("source_label",""), url="") for x in d], "NYC")
p["Simulator Target Bundle"] = "com.luvd.app"
print(json.dumps(p))
PY
xcrun simctl push booted com.luvd.app /tmp/luvd.apns
```

One dog opens straight to that dog. Several open the list filtered to
today's arrivals.

### Turning on real push

The server side is built and inert until four Fly secrets exist
(see `push.py`):

1. Join the Apple Developer Program.
2. In Certificates, Identifiers & Profiles, register the App ID
   `com.luvd.app` with the **Push Notifications** capability.
3. Under Keys, create a key with **Apple Push Notifications service (APNs)**.
   Download the `.p8` — Apple only lets you download it once.
4. Set the secrets:

```bash
fly secrets set APNS_KEY_ID=XXXXXXXXXX APNS_TEAM_ID=YYYYYYYYYY APNS_BUNDLE_ID=com.luvd.app -a luvd-nyc
fly secrets set "APNS_KEY=$(cat AuthKey_XXXXXXXXXX.p8)" -a luvd-nyc
```

The nightly run then pushes each city's new dogs to that city's devices.
`PUSH_PAUSED` stops sends without touching email.

A debug build registers a **sandbox** token and a TestFlight/App Store build
registers a **production** token; the server records which and sends to the
matching APNs host.

## On your phone

In Xcode: select the LUVD target → Signing & Capabilities → choose your team.
Plug in the phone, select it as the run destination, press Run. The bundle id
may need changing (e.g. `com.yourname.luvd`) if `com.luvd.app` is not
registered to your team.

## Layout

| File | What |
|---|---|
| `LUVDApp.swift` | Entry point, push registration, notification taps |
| `AppStore.swift` | All state: city, dogs, filters, saved, deck, push token |
| `API.swift` | `/api/dogs` with page fallback, device registration, view/apply counters |
| `Models.swift` | `Dog` and friends, decoded tolerantly |
| `Filters.swift` | Filter model; buckets and orders mirror the website's |
| `ImagePipeline.swift` | Photo loading with decode-time downsampling |
| `RootView.swift` | Onboarding and tabs |
| `BrowseView.swift` | Search, quick filters, grid |
| `DogDetailView.swift` | Profile: photos, fit, size, cost, similar dogs |
| `DiscoverView.swift` | Swipe deck |
| `SavedSettingsFilters.swift` | Saved, Settings, filter sheet |

The app icon is generated: `.venv/bin/python tools/make_app_icon.py`.
