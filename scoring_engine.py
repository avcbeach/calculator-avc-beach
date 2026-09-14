"""
scoring_engine.py
------------------
Given a player's full BeachTeams career history (as parsed from a VIS
GetPlayer response) plus a cutoff date and a scoring template, compute:

  - the FIVB-side best-N results (with caps)
  - the AVC-side best-N results (with caps, incl. shared multisport/zonal cap)
  - the total points for the player

This module has no VIS/network dependency so it can be unit tested directly
against the sample XML files.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

from classification import classify_tournament, DEFAULT_TEMPLATE


@dataclass
class CareerResult:
    tournament_code: str
    tournament_name: str
    season: str
    end_date: date
    teammate: str
    teammate_no: str
    rank: Optional[int]
    points: int
    tournament_type: int
    organizer_code: str
    country_code: str


@dataclass
class SelectedResult(CareerResult):
    bucket: str = ""


@dataclass
class PlayerScore:
    fivb_selected: List[SelectedResult] = field(default_factory=list)
    avc_selected: List[SelectedResult] = field(default_factory=list)
    unclassified: List[CareerResult] = field(default_factory=list)

    @property
    def fivb_total(self) -> int:
        return sum(r.points for r in self.fivb_selected)

    @property
    def avc_total(self) -> int:
        return sum(r.points for r in self.avc_selected)

    @property
    def total(self) -> int:
        return self.fivb_total + self.avc_total


def _select_best_with_caps(results: List[SelectedResult], max_events: int,
                            caps: dict, shared_cap_groups: List[List[str]]) -> List[SelectedResult]:
    """
    Greedy selection: sort by points desc, take results one at a time,
    respecting per-bucket caps and shared-cap groups, until max_events reached.
    """
    results_sorted = sorted(results, key=lambda r: r.points, reverse=True)

    # normalise shared groups: map bucket -> group key
    group_of = {}
    for group in shared_cap_groups:
        key = tuple(sorted(group))
        for b in group:
            group_of[b] = key

    used_count = {}  # cap-key (bucket or shared-group key) -> count used
    selected = []

    for r in results_sorted:
        if len(selected) >= max_events:
            break
        cap_key = group_of.get(r.bucket, r.bucket)
        limit = caps.get(r.bucket)
        if limit is None and cap_key in caps:
            limit = caps[cap_key]
        if limit is not None:
            if used_count.get(cap_key, 0) >= limit:
                continue  # cap reached for this bucket/group, skip
        selected.append(r)
        used_count[cap_key] = used_count.get(cap_key, 0) + 1

    return selected


def _apply_global_shared_caps(fivb_candidates: List[SelectedResult],
                               avc_candidates: List[SelectedResult],
                               global_cap_groups: List[dict]) -> tuple:
    """
    Some caps apply across BOTH sides combined, not per side - e.g. "only 1
    Multi-sport or Zonal/Regional event to be included in TOTAL", which
    could otherwise let one multi-sport result count on the FIVB side (host
    country not in AVC) AND a different one count on the AVC side (host
    country in AVC) at the same time.

    For each {"buckets": [...], "limit": N} group, keep only the top-N
    highest-points candidates across both sides combined whose bucket is in
    that group, and drop the rest entirely (from whichever side they were
    in) before per-side best-N selection runs.
    """
    for group in global_cap_groups:
        buckets = set(group["buckets"])
        limit = group["limit"]
        tagged = [(r, "fivb") for r in fivb_candidates if r.bucket in buckets]
        tagged += [(r, "avc") for r in avc_candidates if r.bucket in buckets]
        if len(tagged) <= limit:
            continue
        tagged.sort(key=lambda pair: pair[0].points, reverse=True)
        keep_ids = {id(r) for r, _ in tagged[:limit]}
        fivb_candidates = [r for r in fivb_candidates if r.bucket not in buckets or id(r) in keep_ids]
        avc_candidates = [r for r in avc_candidates if r.bucket not in buckets or id(r) in keep_ids]
    return fivb_candidates, avc_candidates


def find_current_partner(career: List[CareerResult], cutoff_date: date,
                          lookback_days: int = 365) -> Optional[dict]:
    """
    Look at this player's results within the lookback window ending at
    cutoff_date and return their most common partner in that window (ties
    broken by most recent result together), as {"no": ..., "name": ...} -
    or None if they have no results with a partner in the window.

    Used to build "current teams" (only pairs who've actually played
    together recently) instead of hypothetical player-vs-player combos.
    """
    lookback_start = cutoff_date - timedelta(days=lookback_days)
    in_window = [r for r in career
                 if r.teammate_no and lookback_start <= r.end_date <= cutoff_date]
    if not in_window:
        return None

    counts: dict = {}
    most_recent: dict = {}
    for r in in_window:
        counts[r.teammate_no] = counts.get(r.teammate_no, 0) + 1
        if r.teammate_no not in most_recent or r.end_date > most_recent[r.teammate_no].end_date:
            most_recent[r.teammate_no] = r

    best_no = max(counts.keys(), key=lambda no: (counts[no], most_recent[no].end_date))
    return {"no": best_no, "name": most_recent[best_no].teammate}


def score_player(career: List[CareerResult], cutoff_date: date,
                  template: dict, avc_country_codes: set) -> PlayerScore:
    """
    career            : full list of CareerResult built from GetPlayer/BeachTeams
    cutoff_date       : the reference date (GTM - 35 for Entry, GTM - 1 for Seeding)
    template          : a scoring template dict (see classification.DEFAULT_TEMPLATE)
    avc_country_codes : set of host-country codes considered "in AVC"
    """
    lookback_start = cutoff_date - timedelta(days=template.get("lookback_days", 365))

    fivb_candidates: List[SelectedResult] = []
    avc_candidates: List[SelectedResult] = []
    unclassified: List[CareerResult] = []

    for r in career:
        if r.points is None:
            continue  # did not actually play / no points earned
        if not (lookback_start <= r.end_date <= cutoff_date):
            continue

        cls = classify_tournament(r.tournament_type, r.organizer_code,
                                   r.country_code, avc_country_codes)
        if cls.side == "EXCLUDED":
            continue
        if cls.side == "FIVB":
            fivb_candidates.append(SelectedResult(**r.__dict__, bucket=cls.bucket))
        elif cls.side == "AVC":
            avc_candidates.append(SelectedResult(**r.__dict__, bucket=cls.bucket))
        else:
            unclassified.append(r)

    fivb_candidates, avc_candidates = _apply_global_shared_caps(
        fivb_candidates, avc_candidates,
        # fall back to the standard rule if an older/custom template on disk
        # predates this field, so the "1 multi-sport/zonal in TOTAL" rule
        # still applies even to templates saved before this fix.
        template.get("global_cap_groups", DEFAULT_TEMPLATE["global_cap_groups"]),
    )

    fivb_cfg = template["fivb_side"]
    avc_cfg = template["avc_side"]

    fivb_selected = _select_best_with_caps(
        fivb_candidates, fivb_cfg["max_events"], fivb_cfg.get("caps", {}),
        fivb_cfg.get("shared_cap_groups", []),
    )
    avc_selected = _select_best_with_caps(
        avc_candidates, avc_cfg["max_events"], avc_cfg.get("caps", {}),
        avc_cfg.get("shared_cap_groups", []),
    )

    return PlayerScore(fivb_selected=fivb_selected, avc_selected=avc_selected,
                        unclassified=unclassified)
