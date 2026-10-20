"""
excel_export.py
----------------
Writes a workbook that matches the structure of the AVC template you
provided (2026_AVC_Beach_Tour_Yunyang_Open... .xlsx) - black & white,
bold headings + borders only, plus an optional logo:

  Sheet "Entry List": Main Draw + Reserve tables with Pos/NF/Team/Player
                        AVC & FIVB points/Team Total, sorted by total desc.
  One "Breakdown" sheet PER FEDERATION: per-player "AVC Side - Best N" and
                        "FIVB Side - Best N" tables with Season/Date/Event
                        Type/Tournament/Teammate/Rank/Points + a total row.
"""

from dataclasses import dataclass
from typing import List, Optional

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XLImage

from scoring_engine import PlayerScore, SelectedResult

# ---------------------------------------------------------------------
# Style constants - black & white only, no fills
# ---------------------------------------------------------------------
FONT_NAME = "Arial"
TITLE_FONT = Font(name=FONT_NAME, bold=True, size=16)
SUBTITLE_FONT = Font(name=FONT_NAME, size=11)
SECTION_FONT = Font(name=FONT_NAME, bold=True, size=12)
HEADER_FONT = Font(name=FONT_NAME, bold=True, size=10)
BODY_FONT = Font(name=FONT_NAME, size=10)
BOLD_BODY_FONT = Font(name=FONT_NAME, bold=True, size=10)
NAME_FONT = Font(name=FONT_NAME, bold=True, size=12)

THIN = Side(style="thin", color="000000")
CELL_BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
BOTTOM_THICK = Border(bottom=Side(style="medium", color="000000"))
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center")


def _bucket_label(bucket: str, tournament_name: str) -> str:
    name = (tournament_name or "").lower()
    if bucket == "pro_tour":
        if "elite" in name:
            return "Pro Tour Elite16"
        if "challenge" in name:
            return "Pro Tour Challenge"
        if "futures" in name:
            return "Pro Tour Futures"
        if "final" in name:
            return "Pro Tour Finals"
        return "Pro Tour"
    return {
        "national_tour": "National Tour",
        "world_championship": "World Championship",
        "olympics": "Olympic Games",
        "multisport": "Zonal Event/Multiple Sports Games",
        "continental_tour": "Continental Tour",
        "zonal": "Zonal Event/Multiple Sports Games",
        "championship": "Continental Championship",
        "underage": "Under-age Championship",
    }.get(bucket, bucket)


@dataclass
class TeamRow:
    pos: int
    nf: str
    team_name: str
    player1_name: str
    player1_avc: int
    player1_fivb: int
    player2_name: str
    player2_avc: int
    player2_fivb: int

    @property
    def total(self) -> int:
        return self.player1_avc + self.player1_fivb + self.player2_avc + self.player2_fivb


@dataclass
class PlayerBreakdown:
    player_name: str
    federation_code: str
    score: PlayerScore
    max_events: int = 4  # for the "Best N" label


def _merge_and_style(ws, row, start_col, end_col, value, font, align=CENTER, height=None, border=False):
    ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=end_col)
    cell = ws.cell(row=row, column=start_col, value=value)
    cell.font = font
    cell.alignment = align
    if border:
        for col in range(start_col, end_col + 1):
            ws.cell(row=row, column=col).border = CELL_BORDER
    if height:
        ws.row_dimensions[row].height = height
    return cell


def _style_header_row(ws, row, headers):
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=col, value=h)
        c.font = HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = CELL_BORDER
    ws.row_dimensions[row].height = 30


def _style_data_row(ws, row, values, ncols, bold_last=False):
    for col in range(1, ncols + 1):
        val = values[col - 1] if col - 1 < len(values) else None
        c = ws.cell(row=row, column=col, value=val)
        c.font = BOLD_BODY_FONT if (bold_last and col == ncols) else BODY_FONT
        c.border = CELL_BORDER
        is_number = isinstance(val, (int, float)) or (isinstance(val, str) and val.startswith("="))
        c.alignment = CENTER if col == 1 or is_number else LEFT


def _sheet_ref(sheet_title: str, col_letter: str, row: int) -> str:
    """Absolute cross-sheet reference, e.g. 'CHN Breakdown'!$G$12. Absolute
    ($) so the Entry List can still be sorted in Excel without the
    references drifting."""
    quoted = sheet_title.replace("'", "''")
    return f"'{quoted}'!${col_letter}${row}"


def _write_entry_list_section(ws, start_row: int, title: str, teams: List[TeamRow],
                               cell_map: dict) -> int:
    headers = ["Pos.", "NF", "Team Name", "Player 1", "Player 1 FIVB Points",
               "Player 1 AVC Points", "Player 2", "Player 2 FIVB Points",
               "Player 2 AVC Points", "Team Total Points"]
    ncols = len(headers)

    _merge_and_style(ws, start_row, 1, ncols, f"{title} ({len(teams)} Teams)",
                      SECTION_FONT, align=LEFT, height=22)
    header_row = start_row + 1
    _style_header_row(ws, header_row, headers)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1).coordinate

    def points_cell(team: TeamRow, player_name: str, side: str, static_value: int):
        """Link to the player's total on their Breakdown tab so edits there
        flow through; fall back to the plain number if the player has no
        Breakdown block (shouldn't normally happen)."""
        loc = cell_map.get((team.nf, player_name))
        if loc is None:
            return static_value
        return "=" + _sheet_ref(loc["sheet"], loc[f"{side}_col"], loc[f"{side}_row"])

    teams_sorted = sorted(teams, key=lambda t: t.total, reverse=True)
    first = header_row + 1
    last = header_row + len(teams_sorted)
    r = first
    for t in teams_sorted:
        row_vals = [
            f"=RANK(J{r},$J${first}:$J${last})",   # Pos. recalculates if totals change
            t.nf, t.team_name,
            t.player1_name,
            points_cell(t, t.player1_name, "fivb", t.player1_fivb),
            points_cell(t, t.player1_name, "avc", t.player1_avc),
            t.player2_name,
            points_cell(t, t.player2_name, "fivb", t.player2_fivb),
            points_cell(t, t.player2_name, "avc", t.player2_avc),
            f"=SUM(E{r}:F{r},H{r}:I{r})",
        ]
        _style_data_row(ws, r, row_vals, ncols, bold_last=True)
        r += 1
    return r + 1  # next free row (with one blank line gap)


def write_entry_list_sheet(ws, event_title: str, event_subtitle: str, gender_label: str,
                            main_draw: List[TeamRow], reserve: List[TeamRow],
                            logo_path: Optional[str] = None,
                            cell_map: Optional[dict] = None):
    cell_map = cell_map or {}
    ncols = 10
    top_row = 1
    widths = {"A": 6, "B": 8, "C": 24, "D": 22, "E": 12, "F": 12, "G": 22, "H": 12, "I": 12, "J": 14}
    if logo_path:
        # Logo on its own tall first row, centred across the whole table width
        # (like the AVC entry-list template); the titles start on row 2.
        try:
            from openpyxl.drawing.spreadsheet_drawing import TwoCellAnchor, AnchorMarker
            from openpyxl.utils.units import pixels_to_EMU
            img = XLImage(logo_path)
            ratio = img.width / img.height if img.height else 1
            h_px = 120
            w_px = int(h_px * ratio)
            # Anchor the logo to CELLS, symmetric around the exact centre of the table
            # (the boundary between the left and right halves of the columns), so it
            # stays centred whatever pixel width Excel gives a character.
            px = [int(w * 7 + 5) for w in widths.values()]          # column widths in px
            half = len(px) // 2
            cols_left, cols_right = px[:half][::-1], px[half:]      # walking away from the centre
            if sum(px[:half]) != sum(px[half:]):                    # table not symmetric: fall back
                pass
            def locate(cols, dist):
                for i, cw in enumerate(cols):
                    if dist <= cw:
                        return i, dist
                    dist -= cw
                return len(cols) - 1, cols[-1]
            li, ld = locate(cols_left, w_px / 2)                    # px from the left edge of that column's right side
            ri, rd = locate(cols_right, w_px / 2)
            from_col = half - 1 - li
            from_off = cols_left[li] - ld
            to_col = half + ri
            img.anchor = TwoCellAnchor(
                editAs="oneCell",
                _from=AnchorMarker(col=from_col, colOff=pixels_to_EMU(int(from_off)), row=0, rowOff=pixels_to_EMU(4)),
                to=AnchorMarker(col=to_col, colOff=pixels_to_EMU(int(rd)), row=0, rowOff=pixels_to_EMU(4 + h_px)))
            ws.add_image(img)
            ws.row_dimensions[1].height = 96
            top_row = 2
        except Exception:
            top_row = 1   # bad/unsupported image file - skip the logo, don't fail the export

    _merge_and_style(ws, top_row, 1, ncols, event_title, TITLE_FONT, height=28)
    _merge_and_style(ws, top_row + 1, 1, ncols, event_subtitle, SUBTITLE_FONT, height=20)
    _merge_and_style(ws, top_row + 2, 1, ncols, f"Confirmed Entry List - {gender_label}'s",
                      SUBTITLE_FONT, height=20)

    next_row = _write_entry_list_section(ws, top_row + 4, "Main Draw", main_draw, cell_map)
    if reserve:
        _write_entry_list_section(ws, next_row, "Reserve", reserve, cell_map)

    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    # print on one page width, landscape
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True


def _write_side_block(ws, row: int, side_label: str, max_events: int,
                       results: List[SelectedResult], ncols: int = 7):
    """Writes one "<side> - Best N" table. Returns (next_row, total_row).

    The Total cell is a live =SUM over the Points column, from the header
    row down to one spare blank row. Including the header (text, ignored by
    SUM) means a row inserted right under it is still counted; the spare
    blank row at the bottom is where a new result can simply be typed in,
    and inserting rows above it expands the range automatically."""
    points_col = get_column_letter(ncols)
    _merge_and_style(ws, row, 1, ncols, f"{side_label} - Best {max_events}",
                      BOLD_BODY_FONT, align=LEFT, height=18)
    row += 1
    header_row = row
    headers = ["Season", "Date", "Event Type", "Tournament", "Teammate", "Rank", "Points"]
    _style_header_row(ws, row, headers)
    row += 1
    for r in results:
        row_vals = [r.season, r.end_date, _bucket_label(r.bucket, r.tournament_name),
                    r.tournament_name, r.teammate, r.rank, r.points]
        _style_data_row(ws, row, row_vals, ncols)
        row += 1
    _style_data_row(ws, row, [None] * ncols, ncols)   # spare row for additions
    spare_row = row
    row += 1

    total_row = row
    tc = ws.cell(row=total_row, column=ncols,
                 value=f"=SUM({points_col}{header_row}:{points_col}{spare_row})")
    tc.font = BOLD_BODY_FONT
    tc.border = BOTTOM_THICK
    row += 2  # blank line after total
    return row, total_row


def write_breakdown_sheet(ws, players: List[PlayerBreakdown]) -> dict:
    """Writes every player's FIVB/AVC blocks on this sheet. Returns
    {(federation_code, player_name): {"sheet", "fivb_col", "fivb_row",
    "avc_col", "avc_row"}} - where each side's Total cell lives - so the
    Entry List can link to them with formulas."""
    ncols = 7
    points_col = get_column_letter(ncols)
    locations = {}
    row = 1
    for pb in players:
        _merge_and_style(ws, row, 1, ncols, f"{pb.player_name} ({pb.federation_code})",
                          NAME_FONT, align=LEFT, height=22)
        row += 1
        row, fivb_total_row = _write_side_block(ws, row, "FIVB Side", pb.max_events,
                                                 pb.score.fivb_selected, ncols)
        row, avc_total_row = _write_side_block(ws, row, "AVC Side", pb.max_events,
                                                pb.score.avc_selected, ncols)
        locations[(pb.federation_code, pb.player_name)] = {
            "sheet": ws.title,
            "fivb_col": points_col, "fivb_row": fivb_total_row,
            "avc_col": points_col, "avc_row": avc_total_row,
        }
        row += 1  # extra gap between players

    for col_letter, width in [("A", 10), ("B", 12), ("C", 22), ("D", 42), ("E", 22), ("F", 8), ("G", 10)]:
        ws.column_dimensions[col_letter].width = width
    return locations


def _safe_sheet_name(name: str, used: set) -> str:
    """Excel sheet names: <=31 chars, no []:*?/\\, must be unique."""
    for ch in "[]:*?/\\":
        name = name.replace(ch, "")
    name = (name or "Unknown")[:31]
    base, n = name, 2
    while name in used:
        suffix = f" ({n})"
        name = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(name)
    return name


def build_workbook(event_title: str, event_subtitle: str, gender_label: str,
                    main_draw: List[TeamRow], reserve: List[TeamRow],
                    players: List[PlayerBreakdown], output_path: str,
                    logo_path: Optional[str] = None):
    from dataclasses import replace as _replace
    from country_codes import excel_code
    main_draw = [_replace(t, nf=excel_code(t.nf)) for t in main_draw]
    reserve = [_replace(t, nf=excel_code(t.nf)) for t in reserve]
    players = [_replace(p, federation_code=excel_code(p.federation_code)) for p in players]

    wb = Workbook()
    ws_entry = wb.active
    ws_entry.title = "Entry List"

    # One Breakdown tab per federation, in NF-code alphabetical order, instead
    # of one long combined sheet. These are written FIRST so we know where
    # each player's totals live, then the Entry List links to them.
    by_federation: dict = {}
    for pb in players:
        by_federation.setdefault(pb.federation_code or "Unknown", []).append(pb)

    cell_map: dict = {}
    used_sheet_names = {"Entry List"}
    for fed_code in sorted(by_federation.keys()):
        sheet_name = _safe_sheet_name(f"{fed_code} Breakdown", used_sheet_names)
        ws = wb.create_sheet(sheet_name)
        cell_map.update(write_breakdown_sheet(ws, by_federation[fed_code]))

    write_entry_list_sheet(ws_entry, event_title, event_subtitle, gender_label,
                            main_draw, reserve, logo_path=logo_path, cell_map=cell_map)

    wb.calculation.fullCalcOnLoad = True   # make Excel compute all formulas on open
    wb.save(output_path)
