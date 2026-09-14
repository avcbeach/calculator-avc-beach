"""
classification.py
------------------
Maps a FIVB VIS BeachTournament record (Type + OrganizerCode + CountryCode)
to one of the buckets used by the AVC Entry/Seeding point rules.

The mapping below was derived by inspecting ~9,300 real BeachTournament
records pulled from VIS (all seasons, all confederations). It is NOT an
official FIVB document - it is a best-effort reconstruction. Any event whose
Type code is not recognised is returned as ("UNCLASSIFIED", raw_type) so it
can be surfaced to a human for review instead of silently mis-scored.

Confirmed with the user (2026-09):
  - Olympic Games (Type 5)              -> counts, FIVB side
  - Officials training / TEST events    -> excluded entirely
  - Snow Volleyball events              -> excluded entirely (not beach)
"""

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Type-code buckets
# ---------------------------------------------------------------------------

# The 4 sister confederations besides AVC. Any event organised by one of
# these (that isn't a multi-sport game hosted in an AVC country) is neither
# "FIVB" nor "AVC" under the rule text given, so it is excluded outright
# rather than mis-bucketed.
OTHER_CONFEDERATION_CODES = {"CEV", "CSV", "NORCECA", "CAVB"}

# National Tour: domestic circuit run by a single National Federation.
# OrganizerCode for these is normally the 3-letter NF code (or blank for very
# old / cancelled records). Counts on the FIVB side per the rules given.
# (25-31 look like an older parallel numbering for the same concept - seen
# with country-code organizers such as EST/UKR/ITA/CZE in the sample data.)
NATIONAL_TOUR_TYPES = {15, 16, 17, 18, 19, 20, 21, 25, 26, 27, 28, 29, 30, 31}

# FIVB Beach Pro Tour, all star-ratings / eras, OrganizerCode == "" (FIVB itself).
# Includes the pre-2019 "Open/Grand Slam/1-5 star" numbering, the 2017-2021
# "Star" system (32/38/39/40/41/42), and the current Elite16/Challenge/
# Futures/Finals system (51/52/53/54).
FIVB_PRO_TOUR_TYPES = {
    0, 1, 2, 3, 6, 13, 14, 32, 33, 36, 42,
    38, 39, 40, 41, 49, 50, 51, 52, 53, 54, 55,
}

FIVB_WORLD_CHAMPIONSHIP_TYPES = {4}
FIVB_OLYMPICS_TYPES = {5}

# Multi-sport games (Asian Games, Commonwealth Games, All-Africa Games, ...).
# Side (FIVB vs AVC) is decided by host country, not by this set alone.
MULTISPORT_TYPES = {8, 34, 44}

# AVC-run categories (OrganizerCode == "AVC")
AVC_CONTINENTAL_TOUR_TYPES = {12}
AVC_ZONAL_TYPES = {11}
AVC_CHAMPIONSHIP_TYPES = {7}
AVC_UNDERAGE_TYPES = {22, 23, 24, 47, 48}

# Explicitly excluded no matter what (test events, snow volleyball, etc.)
EXCLUDED_TYPES = {35, 45, 46, 9}
# 9 = "Goodwill Games / FIVB Seminar" one-off admin records, not real results
# 35 = officials training / VIS clinic / test events
# 45, 46 = Snow Volleyball (not beach volleyball)


@dataclass
class Classification:
    side: str          # "FIVB", "AVC", or "EXCLUDED" / "UNCLASSIFIED"
    bucket: str         # e.g. "pro_tour", "national_tour", "continental_tour"


def classify_tournament(tournament_type: int, organizer_code: str,
                         country_code: str, avc_country_codes: set) -> Classification:
    """
    tournament_type : int, the VIS <Type> attribute
    organizer_code  : str, the VIS <OrganizerCode> attribute ("" if blank)
    country_code    : str, host country of the event (2-letter VIS country code)
    avc_country_codes: set of 2-letter host-country codes considered "in AVC"
                        (build this from VIS federation/confederation data,
                        see vis_client.get_avc_country_codes)
    """
    t = tournament_type
    org = (organizer_code or "").strip().upper()

    if t in EXCLUDED_TYPES:
        return Classification("EXCLUDED", "test_or_snow")

    if t in NATIONAL_TOUR_TYPES and org not in OTHER_CONFEDERATION_CODES:
        return Classification("FIVB", "national_tour")

    if org == "" and t in FIVB_PRO_TOUR_TYPES:
        return Classification("FIVB", "pro_tour")

    if org == "" and t in FIVB_WORLD_CHAMPIONSHIP_TYPES:
        return Classification("FIVB", "world_championship")

    if org == "" and t in FIVB_OLYMPICS_TYPES:
        return Classification("FIVB", "olympics")

    if t in MULTISPORT_TYPES:
        if org == "AVC" or (country_code or "").strip().upper() in avc_country_codes:
            return Classification("AVC", "multisport")
        else:
            return Classification("FIVB", "multisport")

    if org == "AVC":
        if t in AVC_CONTINENTAL_TOUR_TYPES:
            return Classification("AVC", "continental_tour")
        if t in AVC_ZONAL_TYPES:
            return Classification("AVC", "zonal")
        if t in AVC_CHAMPIONSHIP_TYPES:
            return Classification("AVC", "championship")
        if t in AVC_UNDERAGE_TYPES:
            return Classification("AVC", "underage")

    if org in OTHER_CONFEDERATION_CODES:
        # e.g. a CEV/CSV/NORCECA/CAVB continental tour, zonal cup, championship
        # or under-age event: not sanctioned by FIVB or AVC, so it does not
        # contribute to either side under the rule text given.
        return Classification("EXCLUDED", "other_confederation")

    return Classification("UNCLASSIFIED", f"type_{t}_org_{org or 'blank'}")


# ---------------------------------------------------------------------------
# Default scoring template
# ---------------------------------------------------------------------------
# A "template" controls how many best results count per side and any caps.
# Users can create additional templates from the Streamlit UI; they are
# stored as JSON in templates_store.json (see templates.py).

DEFAULT_TEMPLATE = {
    "name": "Standard AVC Rule (Entry/Seeding)",
    "lookback_days": 365,
    # Caps that apply ACROSS both sides combined, checked before the
    # per-side best-N selection below. This is what enforces "only 1
    # Multi-sport or Zonal/Regional event in TOTAL" even though a
    # multi-sport game can land on either side depending on host country.
    "global_cap_groups": [
        {"buckets": ["multisport", "zonal"], "limit": 1},
    ],
    "fivb_side": {
        "max_events": 4,
        "caps": {},  # no other special caps on the FIVB side per current rules
    },
    "avc_side": {
        "max_events": 4,
        "caps": {
            "championship": 1,  # only 1 AVC Championship event counted
        },
        "shared_cap_groups": [],
    },
}
