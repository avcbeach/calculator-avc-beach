"""Excel export for the Asian Rankings page (black & white, FIVB before AVC)."""
from datetime import date, datetime
from typing import Dict, List, Optional

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from country_codes import excel_code
from excel_export import PlayerBreakdown, write_breakdown_sheet, _sheet_ref

FONT = "Arial"
THIN = Side(style="thin", color="000000")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
BLACK = PatternFill("solid", fgColor="000000")
HEADERS = ["Rank", "NF", "Player 1", "Player 1\nFIVB Points", "Player 1\nAVC Points",
           "Player 2", "Player 2\nFIVB Points", "Player 2\nAVC Points", "Team Total\nPoints", "Events\ntogether", "Last event\ntogether"]
WIDTHS = [7, 7, 30, 12, 12, 30, 12, 12, 13, 11, 13]


def build_ranking_workbook(title: str, ranking_date: date, rows_by_gender: Dict[str, List[dict]],
                           output_path: str, logo_path: Optional[str] = None, max_events: int = 4):
    wb = Workbook()
    wb.remove(wb.active)
    sheets = {}
    for gender in ("Men", "Women"):
        sheets[gender] = wb.create_sheet(gender)

    # ONE Breakdown tab per category (Men / Women), players in ranking order, so you can scroll
    # down it like the ranking. Every player name on the ranking sheet is a link to his/her
    # block, and every block has a "back to ranking" link. Totals on the ranking sheet are
    # formulas pointing at the blocks, so editing a result there updates the ranking row.
    logo_rows = 1 if logo_path else 0
    first_data_row = 1 + logo_rows + 3 + 1        # = hr + 1 below (hr = top + 3)
    cell_maps, bd_names = {}, {}
    for gender in ("Men", "Women"):
        rows = rows_by_gender.get(gender, [])
        order, seen = [], {}
        for i, row in enumerate(rows):
            for nf, nm, sc in ((row["p1_nf"], row["p1"], row["s1"]), (row["p2_nf"], row["p2"], row["s2"])):
                k = (excel_code(nf), nm)
                if k not in seen:
                    seen[k] = first_data_row + i          # first ranking row of this player
                    order.append(PlayerBreakdown(nm, excel_code(nf), sc, max_events))
        bname = f"{gender} Breakdown"
        bd_names[gender] = bname
        bws = wb.create_sheet(bname)
        cmap = write_breakdown_sheet(bws, order)
        bws.column_dimensions["I"].width = 18
        for k, loc in cmap.items():
            c = bws.cell(row=loc["top_row"], column=9, value="↑ Back to ranking")
            c.hyperlink = Hyperlink(ref=c.coordinate, location=f"'{gender}'!A{seen[k]}", display="↑ Back to ranking")
            c.font = Font(name=FONT, size=10, underline="single")
        cell_maps[gender] = cmap

    for gender in ("Men", "Women"):
        rows = rows_by_gender.get(gender, [])
        cmap = cell_maps[gender]
        ws = sheets[gender]
        for i, w in enumerate(WIDTHS):
            ws.column_dimensions[chr(65 + i)].width = w
        top = 1
        if logo_path:
            try:
                img = XLImage(logo_path)
                ratio = img.width / img.height if img.height else 1
                img.height = 90
                img.width = int(90 * ratio)
                ws.add_image(img, "A1")
                ws.row_dimensions[1].height = 70
                top = 2
            except Exception:
                top = 1
        for r, (txt, size, bold) in enumerate(
                [(title, 14, True), (f"{gender} - ranking as of {ranking_date:%d %b %Y}", 11, False)], start=top):
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=11)
            c = ws.cell(row=r, column=1, value=txt)
            c.font = Font(name=FONT, size=size, bold=bold)
            c.alignment = Alignment(horizontal="center", vertical="center")
        hr = top + 3
        ws.row_dimensions[hr].height = 32
        for i, h in enumerate(HEADERS, start=1):
            c = ws.cell(row=hr, column=i, value=h)
            c.font = Font(name=FONT, size=10, bold=True, color="FFFFFF")
            c.fill = BLACK
            c.border = BOX
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        r = hr + 1
        def link(nf, name, side, static):
            loc = cmap.get((excel_code(nf), name))
            return static if loc is None else "=" + _sheet_ref(loc["sheet"], loc[f"{side}_col"], loc[f"{side}_row"])

        for row in rows:
            vals = [row["rank"], excel_code(row["nf"]), row["p1"],
                    link(row["p1_nf"], row["p1"], "fivb", row["p1_fivb"]),
                    link(row["p1_nf"], row["p1"], "avc", row["p1_avc"]),
                    row["p2"],
                    link(row["p2_nf"], row["p2"], "fivb", row["p2_fivb"]),
                    link(row["p2_nf"], row["p2"], "avc", row["p2_avc"]),
                    f"=D{r}+E{r}+G{r}+H{r}", row.get("events"),
                    row["last"].strftime("%d-%b-%Y") if row.get("last") else None]
            for i, v in enumerate(vals, start=1):
                c = ws.cell(row=r, column=i, value=v)
                if i in (3, 6):                      # player name -> jump to the breakdown block
                    loc = cmap.get((excel_code(row["p1_nf"] if i == 3 else row["p2_nf"]), v))
                    if loc:
                        c.hyperlink = Hyperlink(ref=c.coordinate,
                                                location=f"'{bd_names[gender]}'!A{loc['top_row']}", display=str(v))
                c.font = Font(name=FONT, size=10, bold=(i == 9), underline="single" if i in (3, 6) else None)
                c.border = BOX
                c.alignment = Alignment(horizontal="left" if i in (3, 6) else "center", vertical="center")
            r += 1
        ws.freeze_panes = ws.cell(row=hr + 1, column=1)
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_title_rows = f"{hr}:{hr}"
        ws.oddFooter.left.text = f"Generated {datetime.now():%d-%b-%Y %H:%M}"
        ws.oddFooter.right.text = "Page &P of &N"
    wb.calculation.fullCalcOnLoad = True
    wb.save(output_path)
    return output_path
