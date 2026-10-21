"""
pages/3_Referee_Assignment.py - upload VIS match-schedule PDF(s), give the
referee / scorer / line-judge name lists, and download the Referee Assignment
Form (Excel) with drop-down lists in every assignment cell.
"""

import tempfile
import pathlib

import streamlit as st

import common_ui
from referee_export import (parse_schedule_pdf, merge_schedules, read_names_from_form,
                            build_referee_workbook, NameEntry, court_label,
                            read_names_from_any)

st.set_page_config(page_title="Referee Assignment", page_icon="🏁", layout="wide")
common_ui.inject_style()

common_ui.require_login()
common_ui.render_sidebar()

st.title("🏁 Referee Assignment Form")
st.caption("Upload the match schedule PDF(s) from VIS → get the assignment sheet with drop-down lists "
           "(Referees / Scorers / Line judges).")

ROLES = [("referees", "Referees", "1st & 2nd Referee drop-downs"),
         ("scorers", "Scorers", "Scorer & Asst. Scorer drop-downs"),
         ("linejudges", "Line judges", "Line judge 1 & 2 drop-downs")]

# ------------------------------------------------------------ 1. schedule PDFs
with st.container(border=True):
    st.subheader("1. Match schedule PDF")
    st.caption("You can upload several files at once (e.g. Men + Women, or an updated schedule). "
               "If the same match appears twice, the version with real team names wins.")
    pdfs = st.file_uploader("VIS 'Match schedule' PDF(s)", type=["pdf"],
                            accept_multiple_files=True, key="ref_pdfs")

    schedule = None
    if pdfs:
        parsed, problems = [], []
        for f in pdfs:
            try:
                parsed.append(parse_schedule_pdf(f))
            except Exception as e:
                problems.append(f"{f.name}: {e}")
        for p in problems:
            st.error(p)
        if parsed:
            schedule = merge_schedules(parsed)
            days = sorted({m.day for m in schedule.matches})
            courts = sorted({m.court for m in schedule.matches},
                            key=lambda c: (0, 0) if c == "CC" else (1, int(c) if c.isdigit() else 99))
            c1, c2, c3 = st.columns(3)
            c1.metric("Matches", len(schedule.matches))
            c2.metric("Days (sheets)", len(days))
            c3.metric("Courts", ", ".join(court_label(c) for c in courts))
            st.write(f"**{schedule.event_name}**")
            with st.expander("Check the parsed matches", expanded=False):
                st.dataframe([{
                    "Date": m.day.strftime("%d-%b"), "Time": m.time.strftime("%H:%M"),
                    "Court": court_label(m.court), "M/W": m.gender, "No.": m.no, "Round": m.rnd,
                    "Team A": m.team_a, "Team B": m.team_b, "Shown as": m.label(),
                } for m in schedule.matches], use_container_width=True, hide_index=True)

# ------------------------------------------------------------ 2. name lists
with st.container(border=True):
    st.subheader("2. Name lists (feed the drop-downs)")
    st.caption("Fill in the three lists below, or import them from an earlier Referee Assignment Form. "
               "'Scoresheet name' is the short name shown in the drop-down (e.g. Helal M.); "
               "leave it blank and the full name (+ country for referees) is used.")

    if "ref_names_ver" not in st.session_state:
        st.session_state["ref_names_ver"] = 0
        st.session_state["ref_names"] = {k: [] for k, _, _ in ROLES}

    imp = st.file_uploader("Optional: import names from a previous Referee Assignment Form (.xlsx)",
                           type=["xlsx"], key="ref_import")
    if imp is not None and st.session_state.get("ref_imported") != imp.file_id:
        try:
            got = read_names_from_form(imp)
            st.session_state["ref_names"] = {
                k: [{"Name": e.name, "Country": e.country, "Scoresheet name": e.sheet_name} for e in v]
                for k, v in got.items()}
            st.session_state["ref_names_ver"] += 1
            st.session_state["ref_imported"] = imp.file_id
            st.success("Imported: " + ", ".join(f"{len(v)} {k}" for k, v in got.items()))
        except Exception as e:
            st.error(str(e))

    ver = st.session_state["ref_names_ver"]
    tabs = st.tabs([label for _, label, _ in ROLES])
    edited = {}
    for tab, (key, label, hint) in zip(tabs, ROLES):
        with tab:
            st.caption(hint)
            up = st.file_uploader(f"Upload a {label.lower()} list - any Excel / CSV with a Name column and a "
                                  "Country column (replaces the table below)",
                                  type=["xlsx", "xlsm", "csv", "txt"], key=f"ref_up_{key}")
            if up is not None and st.session_state.get(f"ref_up_done_{key}") != up.file_id:
                try:
                    got = read_names_from_any(up, up.name)
                    st.session_state["ref_names"][key] = [
                        {"Name": e.name, "Country": e.country, "Scoresheet name": ""} for e in got]
                    st.session_state[f"ref_up_done_{key}"] = up.file_id
                    st.session_state[f"ref_rv_{key}"] = st.session_state.get(f"ref_rv_{key}", 0) + 1
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
            seed = st.session_state["ref_names"].get(key) or [{"Name": "", "Country": "", "Scoresheet name": ""}]
            rv = st.session_state.get(f"ref_rv_{key}", 0)
            edited[key] = st.data_editor(
                seed, num_rows="dynamic", use_container_width=True, hide_index=True,
                key=f"ref_tbl_{key}_{ver}_{rv}",
                column_config={
                    "Name": st.column_config.TextColumn("Name", width="large"),
                    "Country": st.column_config.TextColumn("Country", max_chars=12, width="small"),
                    "Scoresheet name": st.column_config.TextColumn("Scoresheet name (optional)", width="medium"),
                })


def _entries(tbl):
    rows = tbl if isinstance(tbl, list) else tbl.to_dict("records")
    out = []
    for r in rows:
        nm = str(r.get("Name") or "").strip()
        if nm:
            out.append(NameEntry(nm, str(r.get("Country") or "").strip().upper(),
                                 str(r.get("Scoresheet name") or "").strip()))
    return out


# ------------------------------------------------------------ 3. generate
with st.container(border=True):
    st.subheader("3. Generate")
    names = {k: _entries(v) for k, v in edited.items()}
    st.caption(" · ".join(f"{len(v)} {label.lower()}" for (k, label, _), v in zip(ROLES, names.values())))
    if st.button("Generate Referee Assignment Excel", type="primary", disabled=schedule is None):
        out = str(pathlib.Path(tempfile.gettempdir()) / "Referee_Assignment_Form.xlsx")
        build_referee_workbook(schedule, names, out)
        with open(out, "rb") as f:
            st.session_state["ref_file"] = f.read()
    if schedule is None:
        st.info("Upload at least one match schedule PDF first.")
    if st.session_state.get("ref_file") and schedule is not None:
        st.download_button("⬇️ Download Referee Assignment Form",
                           st.session_state["ref_file"],
                           file_name="Referee_Assignment_Form.xlsx", key="ref_dl")
