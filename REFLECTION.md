# Reflection

**What assumptions did you make?**
The big ones are listed in the README, but the meta-assumption underneath
them is that this service should own the portal credential itself rather
than proxy per-caller logins — the brief describes one utility's ops desk
wanting programmatic access to data behind one shared login, not a
multi-tenant auth system, so I treated the portal account like a service
secret. The other assumption I want to flag explicitly: I never found
anything in the portal that states a timezone for consumption timestamps,
and rather than quietly assuming IST (which is plausible given the Jaipur
geo data), I left them naive and said so in both PROTOCOL.md and the
response model's field description. And on the "bulk export ignores
`page`" behaviour — I assumed that's a stable characteristic of this
system worth designing around, not a bug that might get "fixed" out from
under me; if it were a real production integration I'd want a
canary/monitoring check for exactly that assumption breaking silently.

**Which part was the most difficult, and how did you get unstuck?**
The very first `POST /login` attempt failed with a flat `403 Cross-site
POST form submissions are forbidden` and no other detail — no CSRF token
field in the login form's HTML, no obvious header name to guess. That's
SvelteKit's built-in CSRF guard, which checks the `Origin` header against
the request's own host for any non-GET request, but nothing about the 403
body says so. I got unstuck by recognizing the app's shape (SvelteKit,
from the `_app/immutable/` asset paths and `__sveltekit_*` globals in the
page source) and reasoning from there about what a SvelteKit app checks by
default on form posts, rather than treating it as an app-specific secret
header to reverse-engineer from scratch. Once I added `Origin` (matching
the real browser's same-origin request), login worked immediately. The
second-hardest part was the HMAC export endpoint — not the signing itself
(the JS was right there, unminified enough to read), but confirming what
actually varies in the signed string (method, path, raw query string,
timestamp, in that exact order with `\n` joins) by testing single-field
changes against the real server until only exact matches succeeded.

**If you had another day, what would you improve?**
Two things, in order: first, replacing the flat-TTL cache with something
that can tell "the portal's export secret rotated" apart from "the portal
is actually down," which right now both surface identically as a 401
retried once then a 502 — worth distinguishing so an operator isn't stuck
guessing. Second, I'd actually build the small map/hierarchy-explorer
front end I scoped but skipped; the API already exposes exactly the
endpoints (`/meters/near`, `/hierarchy`) that a "see the network on a map"
view would need, so it's mostly UI work at this point rather than more
investigation.

**What mistake did you make while solving this (there's always one)?**
I initially assumed `/portal/export?page=N` paginated the way
`/portal/dts?page=N` visibly does, and almost wrote the adapter to loop
pages accumulating results — which would have silently produced a list
with ~8x duplicate entries (403 meters × however many pages I looped),
since every page actually returns the full dataset. I caught it only
because I deliberately fetched `page=2` with its own correctly-signed
request and diffed the meter IDs against `page=1` before writing the
loop, rather than trusting the pattern from the other paginated endpoint.
It's the kind of bug that wouldn't have thrown an error anywhere — just
quietly wrong (duplicated) data — which is exactly why I called it out as
its own "quirk" in PROTOCOL.md rather than only fixing it in code.

**If you were reviewing your own submission, what would you criticise?**
The in-memory index is doing a linear scan per query, and while I've
documented that this is fine at ~400 meters and said where it'd break, I
haven't actually load-tested where the wall is — I'm asserting it, not
measuring it, which is a fair thing for a reviewer to push back on. I'd
also flag that my consumption-granularity investigation (PROTOCOL.md §4)
is honestly "I checked five obvious columns and found no correlation," not
an exhaustive statistical study — there could be a pattern I didn't think
to check (e.g. something tied to `meterId` numeric ranges or a
per-session random seed), and I'm presenting a negative result with less
rigor than the positive findings elsewhere in the same document. And
every portal-facing test (adapter + routers) runs against a mock or a
fake, by design — none of it is a live contract test against the real
portal, so a real change on their end (a renamed field, a shifted HMAC
scheme) would surface as a production failure, not a red test run. A
scheduled, non-destructive smoke test against the real portal (hitting
`/portal/keys` + one export call, say) would close that gap and is the
first thing I'd add.
