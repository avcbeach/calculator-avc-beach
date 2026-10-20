"""
manual_results.py
-----------------
Read a VIS "Final Ranking" PDF (BeachTournamentRankingReport) of an event that
is not yet in the players' VIS career, and turn it into per-player results
(team points / 2) that can be added to the points calculation.

Pure Python (pdfplumber + re), no Streamlit.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional

from country_codes import excel_code
from scoring_engine import CareerResult

_ROW = re.compile(r"^(?P<rk>\d+)?(?P<team>[^\d].*?)\s+(?P<cc>[A-Z]{3})\s+"
                  r"(?P<pts>\d[\d,]*)(?:\s+(?P<prize>\d[\d,]*))?\s*$")
_TITLE2 = re.compile(r"^(?P<name>.+?)\s*/\s*(?P<gender>Men|Women)\b.*?(?P<end>\d{1,2}-[A-Za-z]{3}-\d{4})\s*$")


@dataclass
class RankRow:
    rank: Optional[int]
    team: str
    country: str
    points: int


@dataclass
class RankingReport:
    event_name: str = ""
    gender: str = ""            # "Men" / "Women"
    end_date: Optional[date] = None
    rows: List[RankRow] = field(default_factory=list)


def parse_ranking_pdf(file_obj) -> RankingReport:
    import pdfplumber
    rep = RankingReport()
    last_rank = None
    with pdfplumber.open(file_obj) as pdf:
        lines = []
        for page in pdf.pages:
            lines += (page.extract_text() or "").splitlines()
    for ln in lines:
        ln = ln.strip()
        m = _TITLE2.match(ln)
        if m and not rep.event_name:
            rep.event_name = m.group("name").strip()
            rep.gender = m.group("gender")
            try:
                rep.end_date = datetime.strptime(m.group("end"), "%d-%b-%Y").date()
            except ValueError:
                pass
            continue
        m = _ROW.match(ln)
        if not m or "VIS, version" in ln:
            continue
        if m.group("rk"):
            last_rank = int(m.group("rk"))
        rep.rows.append(RankRow(last_rank, m.group("team").strip(), m.group("cc"),
                                int(m.group("pts").replace(",", ""))))
    if not rep.rows:
        raise ValueError("No ranking rows found - is this a VIS 'Final Ranking' report PDF?")
    return rep


# ----------------------------------------------------------------- matching
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _tokens(s: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", _norm(s)) if t]


def _half_score(half: str, player_name: str) -> int:
    """0 = no match. Full words must appear in the name; single letters (initials)
    must be the first letter of some name word."""
    ht, pt = _tokens(half), _tokens(player_name)
    words = [t for t in ht if len(t) > 1]
    if not words:
        return 0
    score = 0
    for t in ht:
        if len(t) == 1:
            if any(p.startswith(t) for p in pt):
                score += 1
            else:
                return 0
        elif t in pt:
            score += 3
        else:
            return 0
    return score


def split_team(team: str) -> List[str]:
    parts = [p.strip() for p in team.split("/")]
    return parts if len(parts) == 2 else [team.strip(), ""]


def match_rows(rows: List[RankRow], candidates: List[dict]) -> List[dict]:
    """candidates: [{no, name, nf, team}] for the players of the loaded event.
    Returns one dict per (row, half): {row, half_idx, half, player_no or ''}."""
    out = []
    for row in rows:
        cc = excel_code(row.country)
        pool = [c for c in candidates if excel_code(c["nf"]) == cc]
        halves = split_team(row.team)
        picked = [None, None]
        # 1) the whole team name equals a team of the entry list
        tn = "".join(_tokens(row.team))
        for c in pool:
            if c.get("team") and "".join(_tokens(c["team"])) == tn and c.get("pair"):
                picked = [c["pair"][0], c["pair"][1]]
                break
        # 2) otherwise match each half by name
        if picked == [None, None]:
            used = set()
            for i, h in enumerate(halves):
                if not h:
                    continue
                scored = sorted(((_half_score(h, c["name"]), c["no"]) for c in pool
                                 if c["no"] not in used), reverse=True)
                scored = [s for s in scored if s[0] > 0]
                if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
                    picked[i] = scored[0][1]
                    used.add(scored[0][1])
        for i, h in enumerate(halves):
            if h:
                out.append({"row": row, "half_idx": i, "half": h, "player_no": picked[i] or ""})
    return out


def build_results(matches: List[dict], names: dict, *, code: str, name: str, season: str,
                  end_date: date, tournament_type: int, organizer_code: str,
                  host_country: str, points_for) -> dict:
    """{player_no: CareerResult}. points_for(match)->int gives the player's points."""
    by_row = {}
    for m in matches:
        by_row.setdefault(id(m["row"]), {})[m["half_idx"]] = m
    res = {}
    for halves in by_row.values():
        for idx, m in halves.items():
            no = m["player_no"]
            if not no:
                continue
            other = halves.get(1 - idx)
            res[no] = CareerResult(
                tournament_code=code, tournament_name=name, season=season, end_date=end_date,
                teammate=(names.get(other["player_no"]) if other and other["player_no"] else (other["half"] if other else "")) or "",
                teammate_no=(other["player_no"] if other else "") or "",
                rank=m["row"].rank, points=int(points_for(m)),
                tournament_type=tournament_type, organizer_code=organizer_code,
                country_code=host_country)
    return res
