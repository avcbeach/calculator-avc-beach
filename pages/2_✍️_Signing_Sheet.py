"""
pages/2_Signing_Sheet.py - generate the team Signature Sheet (Excel) for a
tournament: players with birthdate + AVC/FIVB points + shirt numbers, and
coach rows, in the same layout as the VIS BeachTeamSignaturesSheetReport.
"""

import re
import tempfile
import pathlib
from datetime import date, timedelta

import streamlit as st

import common_ui
from scoring_engine import score_player
from vis_parser import parse_tournament_entry_list, parse_player_birthdates
from signing_export import (SigPerson, SigTeam, build_signing_workbook,
                            format_birthdate, date_range_label)

st.set_page_config(page_title="Signing Sheet", page_icon="✍️", layout="wide")
common_ui.inject_style()

client = common_ui.require_login()
template = common_ui.render_sidebar()

st.title("✍️ Signing Sheet")
st.caption("Generate the team signature sheet (players, birthdates, points, shirt numbers, coaches) as Excel.")


def _season_year(season_str) -> int:
    m = re.search(r"\d{4}", str(season_str or ""))
    return int(m.group()) if m else 0


def _resolve_no(code_or_no: str) -> str:
    value = code_or_no.strip()
    if value.isdigit():
        return value
    lookup = common_ui.load_tournament_lookup(client)
    match = lookup.get(value.upper()) or lookup.get(value)
    if not match or not match.get("no"):
        raise ValueError(f"Could not find tournament code '{value}' in the tournament list.")
    return match["no"]


def _team_labels(pairs):
    """['THA | Doe/Roe', ...] one unique label per team, same order as input."""
    out, seen = [], {}
    for nf, name in pairs:
        base = f"{nf} | {name}"
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    return out


def _reset_results():
    for k in ("sig_data", "sig_birth_warning", "sig_file"):
        st.session_state.pop(k, None)


# ---------------------------------------------------------------- 1. tournament
with st.container(border=True):
    st.subheader("1. Select tournament")
    year_now = date.today().year
    c1, c2, c3 = st.columns([1, 1, 2])
    season_from = c1.number_input("From season", value=year_now - 1, step=1, key="sig_from")
    season_to = c2.number_input("To season", value=year_now + 1, step=1, key="sig_to")
    avc_only = c3.checkbox("AVC-organised events only", value=True, key="sig_avc_only")

    if st.button("Load tournament list", key="sig_load_list"):
        with st.spinner("Fetching tournament list from VIS (can take a moment)..."):
            lookup = common_ui.load_tournament_lookup(client)
        st.success(f"Loaded {len(lookup)} tournaments")

    code_or_no = None
    if "tournament_lookup" in st.session_state:
        options = [
            t for t in st.session_state["tournament_lookup"].values()
            if season_from <= _season_year(t["season"]) <= season_to
            and (not avc_only or t["organizer_code"] == "AVC")
        ]
        options.sort(key=lambda t: t["start_main_draw"] or date.min, reverse=True)
        if options:
            choice = st.selectbox(
                "Tournament", options, key="sig_choice",
                format_func=lambda t: f"{t['code']} — {t['name']} ({t['start_main_draw']})")
            code_or_no = choice["code"]
        else:
            st.warning("No tournaments match - widen the season range or untick 'AVC-organised only'.")

    with st.expander("Or enter a tournament Code / No manually"):
        manual = st.text_input("Tournament No or Code", key="sig_manual")
        if manual:
            code_or_no = manual

    if st.button("Load entry list", type="primary", disabled=not code_or_no, key="sig_load_event"):
        try:
            with st.spinner("Loading..."):
                no = _resolve_no(code_or_no)
                parsed = parse_tournament_entry_list(client.get_tournament_entry_list(no))
                st.session_state["sig_event"] = parsed["event"]
                st.session_state["sig_event_no"] = no
                st.session_state["sig_teams"] = parsed["teams"]
                _reset_results()
            st.success(f"Loaded {parsed['event']['name']} — {len(parsed['teams'])} teams")
        except Exception as e:
            st.error(str(e))

if "sig_event" not in st.session_state:
    st.stop()

ev = st.session_state["sig_event"]
all_teams = st.session_state["sig_teams"]
st.write(f"**{ev['name']}** ({ev['code']}) — {ev.get('start_main_draw')} to {ev.get('end_main_draw')}")

# ---------------------------------------------------------------- 2. settings
with st.container(border=True):
    st.subheader("2. Settings")

    counts = {}
    for t in all_teams:
        counts[t["draw_status"]] = counts.get(t["draw_status"], 0) + 1
    statuses = st.multiselect(
        "Include teams with these statuses", options=list(counts.keys()),
        default=[s for s in counts if s == "Main Draw"], key=f"sig_status_{ev['code']}",
        help="Normal teams count as Main Draw; Deleted / Withdrawn are left out by default.")
    teams = [t for t in all_teams if t["draw_status"] in statuses]
    st.caption(f"{len(teams)} of {len(all_teams)} teams will be on the sheet.")

    c1, c2 = st.columns(2)
    basis = c1.radio("Points shown", ["Seeding points", "Entry points"], horizontal=True,
                     key=f"sig_basis_{ev['code']}")
    default_day = ev.get("start_main_draw") or date.today()
    default_cut = default_day - timedelta(days=1 if basis == "Seeding points" else 35)
    cutoff = c2.date_input("Cutoff date", value=default_cut,
                           key=f"sig_cut_{ev['code']}_{basis}")

    c1, c2 = st.columns(2)
    form_code = c1.text_input("Form code", value="B-1c", key="sig_form_code")
    section = c2.text_input("Sheet title", value="Signature sheet - Main draw", key="sig_section")

    logo_file = st.file_uploader("Optional: logo for the top-left corner (PNG/JPG)",
                                 type=["png", "jpg", "jpeg"], key="sig_logo")

    st.markdown("**Coaches / team officials** (optional)")
    st.caption("One row per coach: pick the team, then type the coach. A team can have several "
               "coaches (add several rows); a team with none gets one empty 'C' row to write in.")
    team_labels = _team_labels([(t.get("federation_code", ""), t["name"]) for t in teams])
    coach_df = st.data_editor(
        [{"Team": "", "Coach name": "", "Birthdate": ""}],
        num_rows="dynamic", use_container_width=True, hide_index=True,
        key=f"sig_coaches_{ev['code']}_{len(teams)}_{'-'.join(sorted(statuses))}",
        column_config={
            "Team": st.column_config.SelectboxColumn("Team", options=team_labels, width="medium"),
            "Coach name": st.column_config.TextColumn("Coach name (Lastname Firstname)"),
            "Birthdate": st.column_config.TextColumn("Birthdate (e.g. 16-Dec-1976)"),
        })

    if st.button("Calculate points & prepare sheet", type="primary", disabled=not teams, key="sig_calc"):
        with st.spinner("Fetching player histories and scoring..."):
            lookup = common_ui.load_tournament_lookup(client)
            avc_countries = common_ui.get_avc_country_codes(client)

            birth = {}
            try:
                birth = parse_player_birthdates(client.get_team_birthdates(st.session_state["sig_event_no"]))
                st.session_state.pop("sig_birth_warning", None)
            except Exception as e:   # birthdates are best-effort
                st.session_state["sig_birth_warning"] = str(e)

            data = []
            for t in teams:
                players = []
                for no, name in ((t["player1_no"], t["player1_name"]), (t["player2_no"], t["player2_name"])):
                    sc = score_player(common_ui.load_player_career(client, no, lookup),
                                      cutoff, template, avc_countries)
                    players.append({"no": no, "name": name, "birth": format_birthdate(birth.get(no)),
                                    "avc": sc.avc_total, "fivb": sc.fivb_total})
                data.append({"nf": t.get("federation_code", ""), "team": t["name"], "players": players})
            st.session_state["sig_data"] = data
        st.success("Done - check the birthdates below, then generate the file.")

# ---------------------------------------------------------------- 3. review + export
if "sig_data" in st.session_state:
    data = st.session_state["sig_data"]

    with st.container(border=True):
        st.subheader("3. Review & export")
        if st.session_state.get("sig_birth_warning"):
            st.warning("Could not read birthdates from VIS - fill them in below (or leave blank). "
                       "VIS said: " + st.session_state["sig_birth_warning"][:300])

        rows = [{"NF": d["nf"], "Team": d["team"], "Player": p["name"], "Birthdate": p["birth"],
                 "AVC pts": p["avc"], "FIVB pts": p["fivb"]}
                for d in data for p in d["players"]]
        edited = st.data_editor(
            rows, use_container_width=True, hide_index=True,
            disabled=["NF", "Team", "Player", "AVC pts", "FIVB pts"],
            key=f"sig_review_{ev['code']}_{len(rows)}")
        st.caption("Only the Birthdate column is editable here.")

        if st.button("Generate Signing Sheet Excel", type="primary", key="sig_generate"):
            coaches_by_team = {}
            for r in (coach_df if isinstance(coach_df, list) else coach_df.to_dict("records")):
                lab = str(r.get("Team") or "").strip()
                nm = str(r.get("Coach name") or "").strip()
                if lab and nm:
                    coaches_by_team.setdefault(lab, []).append(
                        SigPerson(nm, str(r.get("Birthdate") or "").strip()))
            labels = _team_labels([(d["nf"], d["team"]) for d in data])

            sig_teams, i = [], 0
            for d, lab in zip(data, labels):
                ppl = []
                for p in d["players"]:
                    e = edited[i] if isinstance(edited, list) else edited.iloc[i].to_dict()
                    ppl.append(SigPerson(p["name"], str(e.get("Birthdate") or ""), p["avc"], p["fivb"]))
                    i += 1
                sig_teams.append(SigTeam(
                    nf=d["nf"], team_name=d["team"], players=ppl,
                    coaches=list(coaches_by_team.get(lab, [])),
                    total=sum(p.avc + p.fivb for p in ppl)))

            logo_path = None
            if logo_file is not None:
                logo_path = str(pathlib.Path(tempfile.gettempdir()) / f"avc_logo_{logo_file.name}")
                with open(logo_path, "wb") as f:
                    f.write(logo_file.getbuffer())

            gender = "Women" if ev.get("gender") == "1" else "Men"
            subtitle = (f"{ev['name']} / {gender} ● "
                        f"{date_range_label(ev.get('start_main_draw'), ev.get('end_main_draw'))}")
            out_path = str(pathlib.Path(tempfile.gettempdir()) / f"{ev['code']}_signing_sheet.xlsx")
            build_signing_workbook(
                event_title=ev["name"], subtitle_line=subtitle,
                form_label=f"{form_code}   {section}", teams=sig_teams,
                output_path=out_path, logo_path=logo_path)
            with open(out_path, "rb") as f:
                st.session_state["sig_file"] = (f"{ev['code']}_signing_sheet.xlsx", f.read())

        if "sig_file" in st.session_state:
            fname, blob = st.session_state["sig_file"]
            st.download_button("⬇️ Download Signing Sheet", blob, file_name=fname, key="sig_dl")
