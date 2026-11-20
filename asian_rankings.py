"""
asian_rankings.py
-----------------
Asian (AVC) team ranking at a given date, scored exactly like the Entry/Seeding
points: each player's AVC + FIVB points (best-N rules, caps, lookback window of the
selected template), team total = player 1 + player 2.

Pure logic (no Streamlit / network) so it can be tested on its own.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List

from scoring_engine import score_player


@dataclass
class Cand:
    no: str
    name: str
    nf: str
    gender: str          # "Men" / "Women"


def collect_candidates(scanned: list, avc_feds: set) -> Dict[str, Cand]:
    """scanned: [(tournament_dict, [team_dict, ...])]. Players of Main Draw teams whose
    federation is in AVC. Later events overwrite earlier ones (most recent federation wins)."""
    out: Dict[str, Cand] = {}
    for t, teams in sorted(scanned, key=lambda x: x[0].get("end_main_draw") or date.min):
        gender = "Women" if t.get("gender") == "1" else "Men"
        for tm in teams:
            nf = (tm.get("federation_code") or "").upper()
            if nf not in avc_feds or tm.get("draw_status") != "Main Draw":
                continue
            for no, name in ((tm["player1_no"], tm["player1_name"]), (tm["player2_no"], tm["player2_name"])):
                if no:
                    out[no] = Cand(no, name, nf, gender)
    return out


def all_pairs(cands: Dict[str, Cand], careers: dict, cutoff: date, lookback: int) -> Dict[tuple, dict]:
    """EVERY pair that played together inside the window (a player who partnered B and C
    gives two pairs). {(a, b): {"names": {no: name}, "events": n, "last": date}}"""
    start = cutoff - timedelta(days=lookback)
    pairs: Dict[tuple, dict] = {}
    for a in cands:
        for r in careers.get(a, []):
            b = r.teammate_no
            if not b or b == a or not (start <= r.end_date <= cutoff):
                continue
            key = tuple(sorted((a, b)))
            d = pairs.setdefault(key, {"names": {}, "codes": set(), "last": r.end_date})
            d["names"][b] = r.teammate or d["names"].get(b, b)
            d["codes"].add(r.tournament_code)
            d["last"] = max(d["last"], r.end_date)
    for d in pairs.values():
        d["events"] = len(d["codes"])
    return pairs


def rank_teams(cands: Dict[str, Cand], careers: dict, pairs: Dict[tuple, dict], cutoff: date,
               template: dict, avc_countries: set, min_points: int = 1,
               mode: str = "player", fed_of: Dict[str, str] = None,
               avc_feds: set = None) -> Dict[str, List[dict]]:
    """{'Men': [...], 'Women': [...]} one row per pair, sorted by team total (ties share the
    rank). A player's points are his/her whole record, so the same player shows the same
    points in every pair he/she appears in.

    mode="pair": like the FIVB team ranking, a pair is scored ONLY on the results the two
    achieved together (each player's record filtered to that partner, then the same
    best-N / cap rules). Same player in two pairs gets separate points for each."""
    scores: Dict[str, object] = {}

    def sc(no):
        if no not in scores:
            scores[no] = score_player(careers.get(no, []), cutoff, template, avc_countries)
        return scores[no]

    fed_of = fed_of or {}

    out = {"Men": [], "Women": []}
    for (a, b), info in pairs.items():
        ca, cb = cands.get(a), cands.get(b)
        base = ca or cb
        if not base:
            continue
        if mode == "pair":
            sa = score_player([r for r in careers.get(a, []) if r.teammate_no == b],
                              cutoff, template, avc_countries)
            sb = score_player([r for r in careers.get(b, []) if r.teammate_no == a],
                              cutoff, template, avc_countries)
        else:
            sa, sb = sc(a), sc(b)
        total = sa.total + sb.total
        if total < min_points:
            continue
        na = ca.name if ca else info["names"].get(a, a)
        nb = cb.name if cb else info["names"].get(b, b)
        nfa = fed_of.get(a) or (ca.nf if ca else base.nf)      # the player's OWN federation
        nfb = fed_of.get(b) or (cb.nf if cb else base.nf)
        if avc_feds is not None and nfa not in avc_feds and nfb not in avc_feds:
            continue                                            # no AVC player in this pair
        out[base.gender].append({
            "nf": nfa if (avc_feds is None or nfa in avc_feds) else nfb,
            "p1_in": avc_feds is None or nfa in avc_feds, "p2_in": avc_feds is None or nfb in avc_feds,
            "p1": na, "p1_fivb": sa.fivb_total, "p1_avc": sa.avc_total,
            "p2": nb, "p2_fivb": sb.fivb_total, "p2_avc": sb.avc_total,
            "total": total, "events": info["events"], "last": info["last"],
            "p1_nf": nfa, "p2_nf": nfb,
            "p1_no": a, "p2_no": b,
            "w1": sc(a), "w2": sc(b),     # whole-record scores (individual points), whatever the mode
            "s1": sa, "s2": sb,          # full PlayerScore objects (selected results = breakdown)
        })
    for g, rows in out.items():
        rows.sort(key=lambda r: (-r["total"], r["nf"], r["p1"], r["p2"]))
        prev, rank = None, 0
        for i, r in enumerate(rows, start=1):
            if r["total"] != prev:
                rank, prev = i, r["total"]
            r["rank"] = rank
    return out
