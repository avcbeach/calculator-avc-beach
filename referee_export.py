"""
referee_export.py
-----------------
1. parse_schedule_pdf()  - reads a VIS "Match schedule" PDF (BeachMatchResultReport2)
                           into Match objects.
2. build_referee_workbook() - writes the Referee Assignment Form: one "Day N" sheet
                           per match date (time slots x courts, with 1st/2nd Referee,
                           Scorer, Asst. Scorer, Line judge 1/2 drop-downs) plus a
                           "Name List" sheet that feeds the drop-downs.

No Streamlit in here, so it can be tested on its own.
"""

import re
from country_codes import excel_code
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Dict, List, Optional

import pdfplumber
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

FONT = "Calibri"
THIN = Side(style="thin", color="000000")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
GREY = PatternFill("solid", fgColor="D0CECE")
PINK = PatternFill("solid", fgColor="FFCCFF")       # women's matches (as in the template)
BLUE = PatternFill("solid", fgColor="DDEBF7")       # men's matches

ASSIGN_ROWS = ["1st Referee", "2nd Referee", "Scorer", "Asst. Scorer",
               "Line judge 1", "Line judge 2"]
BLOCK_ROWS = 2 + len(ASSIGN_ROWS)                    # match no + teams + 6 assignments

# ----------------------------------------------------------------------------
# PDF parsing
# ----------------------------------------------------------------------------

_TEAM = r"(?:(?:Winner|Loser) of match \d+|.+?\([A-Z]{2,3}\))"
_ROW = re.compile(
    rf"^\s*(\d+)\s+(\S+)\s+(\d{{1,2}}-[A-Za-z]{{3}}(?:-\d{{2,4}})?)\s+({_TEAM})\s+({_TEAM})\s+(?:.*?\s)?(CC|\d+)\s+(\d{{1,2}}:\d{{2}})\s*$"
)
_PLACEHOLDER = re.compile(r"^(Winner|Loser) of match (\d+)$")


@dataclass
class Match:
    no: int
    rnd: str
    day: date
    time: time
    court: str            # 'CC', '2', '3'...
    team_a: str
    team_b: str
    gender: str           # 'M' or 'W'
    placeholder: bool = False

    def label(self) -> str:
        """What goes in the 'teams' row: CHN-JPN, or 'Winner of 27-28'."""
        a, b = self.team_a, self.team_b
        pa, pb = _PLACEHOLDER.match(a), _PLACEHOLDER.match(b)
        if pa and pb:
            if pa.group(1) == pb.group(1):
                return f"{pa.group(1)} of {pa.group(2)}-{pb.group(2)}"
            return f"{pa.group(1)} of {pa.group(2)} - {pb.group(1)} of {pb.group(2)}"
        return f"{_short(a)}-{_short(b)}"


def _short(team: str) -> str:
    m = re.search(r"\(([A-Z]{2,3})\)\s*$", team)
    if m:
        return excel_code(m.group(1))
    m = _PLACEHOLDER.match(team)
    return f"{m.group(1)} of {m.group(2)}" if m else team


@dataclass
class Schedule:
    event_name: str = ""
    matches: List[Match] = field(default_factory=list)


def _page_lines(page) -> List[str]:
    text = page.extract_text(layout=True) or ""
    return [ln for ln in text.splitlines() if ln.strip()]


def parse_schedule_pdf(file_obj) -> Schedule:
    """file_obj: path or binary file-like. Raises ValueError if nothing parsed."""
    sched = Schedule()
    gender, year = "", None
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            lines = _page_lines(page)
            for i, ln in enumerate(lines):
                if not sched.event_name and i == 0:
                    sched.event_name = ln.strip()
                g = re.search(r"/\s*(Men|Women)\b", ln)
                if g:
                    gender = "M" if g.group(1) == "Men" else "W"
                    y = re.findall(r"-(\d{4})\b", ln)
                    if y:
                        year = int(y[-1])
                m = _ROW.match(ln)
                if not m:
                    continue
                no, rnd, dstr, ta, tb, ct, tm = m.groups()
                dd = re.match(r"(\d{1,2})-([A-Za-z]{3})(?:-(\d{2,4}))?", dstr)
                yy = int(dd.group(3)) if dd.group(3) else (year or date.today().year)
                if yy < 100:
                    yy += 2000
                d = datetime.strptime(f"{dd.group(1)}-{dd.group(2)}-{yy}", "%d-%b-%Y").date()
                hh, mm = map(int, tm.split(":"))
                sched.matches.append(Match(
                    no=int(no), rnd=rnd, day=d, time=time(hh, mm), court=ct,
                    team_a=ta.strip(), team_b=tb.strip(), gender=gender or "?",
                    placeholder=bool(_PLACEHOLDER.match(ta.strip()) or _PLACEHOLDER.match(tb.strip()))))
    if not sched.matches:
        raise ValueError("No matches found in this PDF - is it a VIS 'Match schedule' report?")
    return sched


def merge_schedules(schedules: List[Schedule]) -> Schedule:
    """Combine several PDFs (e.g. Men + Women, or an updated version). The same
    (gender, match no.) can appear twice; keep the one with real team names,
    otherwise the one from the later file."""
    out = Schedule(event_name=next((s.event_name for s in schedules if s.event_name), ""))
    best: Dict[tuple, Match] = {}
    for s in schedules:
        for m in s.matches:
            k = (m.gender, m.no)
            old = best.get(k)
            if old is None or not (m.placeholder and not old.placeholder):
                best[k] = m
    out.matches = sorted(best.values(), key=lambda m: (m.day, m.time, _court_key(m.court)))
    return out


def _court_key(c: str):
    return (0, 0) if c == "CC" else (1, int(c) if c.isdigit() else 99)


def court_label(c: str) -> str:
    return "CC" if c == "CC" else f"Court {c}"


# ----------------------------------------------------------------------------
# Name lists
# ----------------------------------------------------------------------------

@dataclass
class NameEntry:
    name: str = ""
    country: str = ""
    sheet_name: str = ""     # short name for the scoresheet; blank -> formula default


def read_names_from_form(file_obj) -> Dict[str, List[NameEntry]]:
    """Import the 'Name List' sheet of an earlier Referee Assignment Form.
    Returns {'referees': [...], 'scorers': [...], 'linejudges': [...]}."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = load_workbook(file_obj, data_only=True)
    if "Name List" not in wb.sheetnames:
        raise ValueError("No 'Name List' sheet found in that file.")
    ws = wb["Name List"]
    result = {"referees": [], "scorers": [], "linejudges": []}
    current = None
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
        a = str(row[0].value or "").strip().lower()
        if a.startswith("referee name"):
            current = "referees"; continue
        if a.startswith("scorer name"):
            current = "scorers"; continue
        if a.startswith("line judge"):
            current = "linejudges"; continue
        if current and len(row) >= 5 and row[1].value and str(row[1].value).strip().lower() != "name":
            sheet_nm = row[4].value
            if isinstance(sheet_nm, str) and sheet_nm.startswith("="):
                sheet_nm = ""
            result[current].append(NameEntry(
                str(row[1].value).strip(), str(row[2].value or "").strip(),
                str(sheet_nm or "").strip()))
    return result


# ----------------------------------------------------------------------------
# Workbook
# ----------------------------------------------------------------------------

def _c(ws, row, col, value=None, *, bold=False, fill=None, h="center", v="center",
       wrap=False, fmt=None, border=True):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = Font(name=FONT, size=11, bold=bold)
    cell.alignment = Alignment(horizontal=h, vertical=v, wrap_text=wrap)
    if fill:
        cell.fill = fill
    if fmt:
        cell.number_format = fmt
    if border:
        cell.border = BOX
    return cell


def _write_name_sheet(wb, event_name: str, names: Dict[str, List[NameEntry]]):
    ws = wb.create_sheet("Name List")
    ws.column_dimensions["A"].width = 4.5
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 9
    ws.column_dimensions["D"].width = 3
    ws.column_dimensions["E"].width = 30
    _c(ws, 1, 1, "Event name: ", bold=True, h="left", border=False)
    _c(ws, 1, 2, event_name, h="left", border=False)

    sections = [("referees", "Referee name list", 20, True),
                ("scorers", "Scorer name list", 10, False),
                ("linejudges", "Line judges name list", 10, False)]
    ranges = {}
    row = 4
    for key, title, min_rows, with_country in sections:
        entries = names.get(key, [])
        size = max(min_rows, len(entries))
        _c(ws, row, 1, title, bold=True, h="left", border=False)
        _c(ws, row, 5, "Scoresheet name ", bold=True, h="left", border=False)
        row += 1
        for col, txt in ((1, "No."), (2, "Name"), (3, "Country"), (5, "Name")):
            _c(ws, row, col, txt, fill=GREY, h="left")
        row += 1
        first = row
        for i in range(size):
            e = entries[i] if i < len(entries) else NameEntry()
            _c(ws, row, 1, i + 1, h="left")
            _c(ws, row, 2, e.name or None, h="left")
            _c(ws, row, 3, (excel_code(e.country) if e.country else None), h="left")
            if e.sheet_name:
                sheet_val = e.sheet_name
            elif with_country:
                sheet_val = f'=IF(B{row}="","",TRIM(B{row}&" "&C{row}))'
            else:
                sheet_val = f'=IF(B{row}="","",B{row})'
            _c(ws, row, 5, sheet_val, h="left")
            row += 1
        ranges[key] = f"'Name List'!$E${first}:$E${row - 1}"
        row += 2
    return ranges


def build_referee_workbook(schedule: Schedule, names: Dict[str, List[NameEntry]],
                           output_path: str):
    wb = Workbook()
    wb.remove(wb.active)

    courts = sorted({m.court for m in schedule.matches}, key=_court_key)
    ncourt = len(courts)
    last_col = 2 + ncourt
    days = sorted({m.day for m in schedule.matches})

    # Name List first in code (to know the ranges), moved to the end afterwards
    ranges = _write_name_sheet(wb, schedule.event_name, names)

    for di, day in enumerate(days, start=1):
        ws = wb.create_sheet(f"Day {di}", index=di - 1)
        ws.column_dimensions["A"].width = 14.7
        ws.column_dimensions["B"].width = 16
        for ci in range(ncourt):
            ws.column_dimensions[chr(ord("C") + ci)].width = 22

        _c(ws, 1, 1, "Date:", border=False)
        _c(ws, 1, 2, day, fmt="d-mmm-yy", border=False)

        # header rows 3-4
        ws.merge_cells("A3:A4"); ws.merge_cells("B3:B4")
        ws.merge_cells(start_row=3, start_column=3, end_row=3, end_column=last_col)
        for r in (3, 4):
            for col in range(1, last_col + 1):
                _c(ws, r, col, None, bold=True, fill=GREY)
        _c(ws, 3, 1, "Match Time", bold=True, fill=GREY)
        _c(ws, 3, 2, "Assigned / Gender ", bold=True, fill=GREY, wrap=True)
        _c(ws, 3, 3, "Court", bold=True, fill=GREY)
        for ci, ct in enumerate(courts):
            _c(ws, 4, 3 + ci, court_label(ct), bold=True, fill=GREY)

        day_matches = [m for m in schedule.matches if m.day == day]
        slots = sorted({m.time for m in day_matches})
        row = 5
        ref_rows, score_rows, lj_rows = [], [], []
        for tm in slots:
            slot = [m for m in day_matches if m.time == tm]
            genders = {m.gender for m in slot}
            gtxt = "/".join(g for g in ("M", "W") if g in genders) or "?"
            top, bottom = row, row + BLOCK_ROWS - 1

            ws.merge_cells(start_row=top, start_column=1, end_row=bottom, end_column=1)
            ws.merge_cells(start_row=top, start_column=2, end_row=top + 1, end_column=2)
            for r in range(top, bottom + 1):
                for col in range(1, last_col + 1):
                    _c(ws, r, col, None)
            _c(ws, top, 1, tm, fmt="h:mm")
            _c(ws, top, 2, gtxt, fill=GREY)
            ws.cell(row=top + 1, column=2).fill = GREY

            for ci, ct in enumerate(courts):
                m = next((x for x in slot if x.court == ct), None)
                if m:
                    fill = PINK if m.gender == "W" else BLUE
                    _c(ws, top, 3 + ci, m.no, fill=fill)
                    _c(ws, top + 1, 3 + ci, m.label(), fill=fill)
            for k, lab in enumerate(ASSIGN_ROWS):
                _c(ws, top + 2 + k, 2, lab)
            ref_rows += [top + 2, top + 3]
            score_rows += [top + 4, top + 5]
            lj_rows += [top + 6, top + 7]
            row = bottom + 1

        def apply_dv(rows, rng):
            if not rows:
                return
            dv = DataValidation(type="list", formula1=rng, allow_blank=True,
                                showErrorMessage=False)
            ws.add_data_validation(dv)
            for r in rows:
                dv.add(f"C{r}:{chr(ord('C') + ncourt - 1)}{r}")

        apply_dv(ref_rows, ranges["referees"])
        apply_dv(score_rows, ranges["scorers"])
        apply_dv(lj_rows, ranges["linejudges"])

        ws.page_setup.orientation = "portrait"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True

    wb.active = 0
    wb.save(output_path)
    return output_path
