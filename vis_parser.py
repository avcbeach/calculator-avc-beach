"""
vis_parser.py
-------------
Pure parsing functions for FIVB VIS XML responses. No network code here -
this only turns already-downloaded XML text into Python objects, so it can
be tested directly against the sample files the user provided.

Covers three response shapes seen so far:
  1. GetPlayer (+BeachTeams)         -> parse_player_career()
  2. GetBeachTournamentList          -> parse_tournament_list()
  3. GetBeachTournament (entry list) -> parse_tournament_entry_list()

NOTE: field names were reverse-engineered from real sample responses, not
from official FIVB documentation. If a live call comes back with a field
under a slightly different name, update the constants below.
"""

from datetime import datetime, date
from typing import List, Optional
import xml.etree.ElementTree as ET

from scoring_engine import CareerResult


def _parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_int(s: str) -> Optional[int]:
    if s is None or s == "":
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_player_career(xml_text: str, player_no: str) -> List[CareerResult]:
    """
    Parse a GetPlayer response (with BeachTeams sub-list) into a list of
    CareerResult, one per BeachTeam entry that player_no took part in as
    Player1 or Player2.
    """
    root = ET.fromstring(xml_text)
    results = []
    for bt in root.iter("BeachTeam"):
        no1 = bt.get("NoPlayer1")
        no2 = bt.get("NoPlayer2")
        if player_no not in (no1, no2):
            continue
        teammate = ""
        teammate_no = ""
        if no1 == player_no:
            teammate = f"{bt.get('Player2LastName','')} {bt.get('Player2FirstName','')}".strip()
            teammate_no = no2 or ""
        else:
            teammate = f"{bt.get('Player1LastName','')} {bt.get('Player1FirstName','')}".strip()
            teammate_no = no1 or ""

        end_date = _parse_date(bt.get("TournamentEndDateMainDraw", ""))
        points = _parse_int(bt.get("EarnedPointsPlayer", ""))
        rank = _parse_int(bt.get("Rank", ""))
        t_type = _parse_int(bt.get("TournamentType", "")) or 0
        # NOTE: sample field is literally "TournamentType" per VIS docs, but the
        # sample dump we inspected used the attribute name "TournamentType"
        # in some calls and just "Type" in others (GetBeachTournamentList).
        # Handle both defensively:
        if bt.get("TournamentType") is None and bt.get("Type") is not None:
            t_type = _parse_int(bt.get("Type", "")) or 0

        if end_date is None or points is None:
            continue

        results.append(CareerResult(
            tournament_code=bt.get("TournamentCode", ""),
            tournament_name=bt.get("TournamentName", ""),
            season=bt.get("TournamentSeason", ""),
            end_date=end_date,
            teammate=teammate,
            teammate_no=teammate_no,
            rank=rank,
            points=points,
            tournament_type=t_type,
            organizer_code="",  # not present on BeachTeam rows - filled in later
            country_code=bt.get("CountryCode", ""),
        ))
    return results


def parse_tournament_list(xml_text: str) -> List[dict]:
    """
    Parse a GetBeachTournamentList response into a list of dicts describing
    each tournament: Code, Name, Season, Type, OrganizerCode, CountryCode,
    StartDateMainDraw, EndDateMainDraw.
    Used to build a Type/OrganizerCode -> classification lookup table (by
    TournamentCode) that we merge into player career rows, since the
    GetPlayer/BeachTeams rows do not carry OrganizerCode themselves.
    """
    root = ET.fromstring(xml_text)
    out = []
    for bt in root.iter("BeachTournament"):
        out.append({
            "no": bt.get("No", ""),
            "code": bt.get("Code", ""),
            "name": bt.get("Name", ""),
            "season": bt.get("Season", ""),
            "type": _parse_int(bt.get("Type", "")) or 0,
            "organizer_code": bt.get("OrganizerCode", "") or "",
            "country_code": bt.get("CountryCode", "") or "",
            "start_main_draw": _parse_date(bt.get("StartDateMainDraw", "")),
            "end_main_draw": _parse_date(bt.get("EndDateMainDraw", "")),
            "gender": bt.get("Gender", ""),
        })
    return out


def parse_tournament_entry_list(xml_text: str) -> dict:
    """
    Parse a GetBeachTournament (single event, with embedded BeachTeams/
    Player1/Player2) response into:
      {
        "event": {code, name, type, organizer_code, country_code,
                   start_main_draw, end_main_draw,
                   entry_points_day_offset, seed_points_day_offset},
        "teams": [ {no, name, player1_no, player1_name, player2_no,
                     player2_name}, ... ]
      }
    """
    root = ET.fromstring(xml_text)
    ev = root.find("BeachTournament")
    if ev is None:
        # some responses wrap it directly at root
        ev = root

    event = {
        "code": ev.get("Code", ""),
        "name": ev.get("Name", ""),
        "type": _parse_int(ev.get("Type", "")) or 0,
        "organizer_code": ev.get("OrganizerCode", "") or "",
        "country_code": ev.get("CountryCode", "") or "",
        "start_main_draw": _parse_date(ev.get("StartDateMainDraw", "")),
        "end_main_draw": _parse_date(ev.get("EndDateMainDraw", "")),
        "entry_points_day_offset": _parse_int(ev.get("EntryPointsDayOffset", "")),
        "seed_points_day_offset": _parse_int(ev.get("SeedPointsDayOffset", "")),
        "gender": ev.get("Gender", ""),
    }

    teams = []
    for bt in root.iter("BeachTeam"):
        p1 = bt.find("Player1")
        p2 = bt.find("Player2")
        pos_main = bt.get("PositionInMainDraw", "")
        pos_reserve = bt.get("PositionInReserve", "")
        pos_qualif = bt.get("PositionInQualification", "")
        status_raw = bt.get("Status", "")

        # Confirmed by the user against real VIS data: 0=Normal, 1=Deleted,
        # 2=Withdrawn. That's the only split needed - all Normal teams are
        # treated as Main Draw, full stop (no Reserve/Qualification
        # sub-classification).
        if status_raw == "1":
            draw_status = "Deleted"
        elif status_raw == "2":
            draw_status = "Withdrawn"
        else:
            draw_status = "Main Draw"

        teams.append({
            "no": bt.get("No", ""),
            "name": bt.get("Name", ""),
            "player1_no": p1.get("No", "") if p1 is not None else bt.get("NoPlayer1", ""),
            "player1_name": f"{p1.get('LastName','')} {p1.get('FirstName','')}".strip() if p1 is not None else "",
            "player2_no": p2.get("No", "") if p2 is not None else bt.get("NoPlayer2", ""),
            "player2_name": f"{p2.get('LastName','')} {p2.get('FirstName','')}".strip() if p2 is not None else "",
            "federation_code": bt.get("FederationCode", ""),
            "status_raw": status_raw,
            "position_in_main_draw": pos_main,
            "position_in_reserve": pos_reserve,
            "position_in_qualification": pos_qualif,
            "draw_status": draw_status,
        })
    event["teams"] = None  # placeholder, teams returned separately below
    return {"event": event, "teams": teams}
