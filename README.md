# AVC Entry / Seeding Points Calculator

A tool to calculate AVC Beach Volleyball **Entry Points** and **Seeding Points**
for a tournament's entry list, pulling career results from the FIVB VIS
database, and exporting a report in the same layout as your existing
AVC Excel template (Entry List + Breakdown sheets).

## Quick start

```bash
py -m pip install -r requirements.txt
py -m streamlit run Home.py
```

(use `python3` / `pip` instead of `py` on Mac/Linux)

You'll be asked to log in with your **FIVB VIS username/password** first
(a popup, powered by `st.dialog`) - nothing else in the app is reachable
until that succeeds. Logging in once carries over to every page for the
rest of the browser session; use **Log out** in the sidebar to switch
accounts.

Pages (sidebar navigation):
- **Home** — quick "how this works" overview.
- **Calculator** — the actual tool: pick a tournament, set your own cutoff
  dates, choose a scoring template, export the Excel report.

## How scoring works (`scoring_engine.py` + `classification.py`)

- Each career result already carries `EarnedPointsPlayer` straight from VIS
  - no separate points-by-rank table needed.
- A result counts only if it falls within the lookback window (default 365
  days) ending at the cutoff date, and has a non-blank points value.
- Every result is classified into a bucket (Pro Tour, National Tour, World
  Championship, Olympics, Continental Tour, Zonal, Continental
  Championship, Under-age, Multi-sport-in-AVC, Multi-sport-not-in-AVC) using
  the tournament's `Type` + `OrganizerCode` (+ host country for multi-sport
  games). This mapping was reverse-engineered from ~9,300 real historical
  VIS tournament records (see the big table at the top of
  `classification.py`) - it is **not** an official FIVB document.
- The best N results per side are picked (greedy, highest points first),
  respecting the caps in the active **scoring template** (max events per
  side). The "only 1 Multi-sport/Zonal event in TOTAL" rule is enforced
  *across both sides combined* (see `_apply_global_shared_caps` in
  `scoring_engine.py`), not per side.

## Scoring templates

Editable from the sidebar ("Edit / create template") - no code changes
needed to add e.g. a "Best 3" variant. Stored in `templates_store.json`.

## Known open items / things to double-check with real data

1. **VIS auth style** - hardcoded to HTTP Basic Auth in `vis_client.py`,
   confirmed working against your real server.
2. **`GetFederationList` call** (`vis_client.get_avc_country_codes`) - used
   to decide whether a multi-sport game's host country counts as "in AVC".
   Uses the same confirmed Filter/Relation style as the working calls, but
   hasn't specifically been run live yet - same "share the error if it
   400s" approach applies if it needs a tweak.
3. **Unclassified events report** - any career result that didn't match a
   known bucket is dropped from scoring silently. Flag if you'd like a
   review panel added before relying on this for entries with a lot of
   international results.
4. **Pro Tour tier labels** in the Breakdown sheet ("Pro Tour Challenge" vs
   "Elite16" vs "Futures") are guessed from the tournament name text -
   cosmetic only, doesn't affect point totals.
5. Team status handling: `Status` 0=Normal (treated as Main Draw), 1=Deleted,
   2=Withdrawn - confirmed by the user against real VIS data. Deleted/
   Withdrawn teams are excluded from scoring by default (adjustable on the
   Calculator page); everything else counts as Main Draw, no further
   Reserve/Qualification sub-split.
6. Tournament-list fetches currently pull the **full** VIS list and filter
   client-side, since a working season/date Filter syntax for
   `GetBeachTournamentList` hasn't been confirmed - slower than necessary
   but safe. Pass a working filter once you find one and it can be wired in.

## Developer testing (not part of the running app)

`test_with_samples.py` + the `data/` folder replay the 3 real VIS responses
you provided early on, offline, to sanity-check the classification table and
scoring logic without hitting VIS. Run with `python3 test_with_samples.py`.

## File map

- `Home.py` - landing page + login gate entry point (Streamlit)
- `pages/1_🧮_Calculator.py` - the calculator (Streamlit)
- `common_ui.py` - login dialog, shared sidebar/styling, and data-loading helpers
- `vis_client.py` - HTTP calls to FIVB VIS (network layer)
- `vis_parser.py` - turns VIS XML into plain Python objects (no network)
- `classification.py` - Tournament Type/Organizer -> AVC/FIVB bucket table
- `scoring_engine.py` - date filtering + best-N-with-caps selection
- `excel_export.py` - writes the styled Entry List / per-federation Breakdown workbook (with optional logo)
- `templates.py` - scoring template storage (JSON)
- `test_with_samples.py` / `data/` - offline sanity test (see above)
