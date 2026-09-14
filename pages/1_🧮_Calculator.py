"""
pages/1_Calculator.py - single-tournament Entry/Seeding Points calculator
with a custom cutoff date and a choice of scoring template.
"""

import re
import tempfile
import pathlib
from datetime import date, timedelta

import streamlit as st

import common_ui
from scoring_engine import score_player
from vis_parser import parse_tournament_entry_list
from excel_export import build_workbook, TeamRow, PlayerBreakdown

st.set_page_config(page_title="AVC Points Calculator", page_icon="🧮", layout="wide")
common_ui.inject_style()

client = common_ui.require_login()
template = common_ui.render_sidebar()

st.title("🧮 Entry / Seeding Points Calculator")
st.caption("Score one tournament's entry list, with your own cutoff dates and scoring template.")


def _season_year(season_str) -> int:
    """Seasons are usually a plain year ('2026') but some old records use a
    split-season format like '1991-92' - just take the first 4-digit year
    found, or 0 if nothing parses."""
    m = re.search(r"\d{4}", str(season_str or ""))
    return int(m.group()) if m else 0


def load_event(tournament_code_or_no):
    value = tournament_code_or_no.strip()
    if not value.isdigit():
        lookup = common_ui.load_tournament_lookup(client)
        match = lookup.get(value.upper()) or lookup.get(value)
        if not match or not match.get("no"):
            raise ValueError(
                f"Could not find tournament code '{value}' in the tournament "
                f"list to resolve its numeric No. Double-check the code, or "
                f"enter the numeric No directly if you have it."
            )
        value = match["no"]
    xml = client.get_tournament_entry_list(value)
    st.session_state["last_event_xml"] = xml
    return parse_tournament_entry_list(xml)


with st.container(border=True):
    st.subheader("1. Select tournament")
    year_now = date.today().year
    c1, c2, c3 = st.columns([1, 1, 2])
    season_from = c1.number_input("From season", value=year_now - 1, step=1)
    season_to = c2.number_input("To season", value=year_now + 1, step=1)
    avc_only = c3.checkbox("AVC-organised events only", value=True)

    if st.button("Load tournament list"):
        with st.spinner("Fetching tournament list from VIS (pulls the full list, can take a moment)..."):
            lookup = common_ui.load_tournament_lookup(client)
        st.success(f"Loaded {len(lookup)} tournaments")

    tournament_code_or_no = None
    if "tournament_lookup" in st.session_state:
        lookup = st.session_state["tournament_lookup"]
        options = [
            t for t in lookup.values()
            if season_from <= _season_year(t["season"]) <= season_to
            and (not avc_only or t["organizer_code"] == "AVC")
        ]
        options.sort(key=lambda t: t["start_main_draw"] or date.min, reverse=True)

        if options:
            def _label(t):
                return f"{t['code']} — {t['name']} ({t['start_main_draw']})"

            choice = st.selectbox("Tournament", options, format_func=_label)
            tournament_code_or_no = choice["code"]
        else:
            st.warning("No tournaments match this filter - try widening the season range "
                       "or unchecking 'AVC-organised only'.")

    with st.expander("Or enter a tournament Code / No manually"):
        manual = st.text_input("Tournament No or Code")
        if manual:
            tournament_code_or_no = manual

    if st.button("Load entry list", type="primary", disabled=not tournament_code_or_no):
        try:
            with st.spinner("Loading..."):
                parsed = load_event(tournament_code_or_no)
                st.session_state["event"] = parsed["event"]
                st.session_state["teams"] = parsed["teams"]
                # Loading a (possibly different) tournament invalidates any
                # results calculated for the previous one - clear them so
                # the Results section doesn't keep showing stale data until
                # "Calculate" is pressed again.
                for k in ("entry_team_rows", "seed_team_rows", "entry_reserve_rows",
                          "seed_reserve_rows", "entry_breakdowns", "seed_breakdowns"):
                    st.session_state.pop(k, None)
            st.success(f"Loaded {parsed['event']['name']} — {len(parsed['teams'])} teams")
        except Exception as e:
            st.error(str(e))

    if "last_event_xml" in st.session_state:
        with st.expander("Debug: raw VIS response for the last 'Load entry list' call"):
            st.code(st.session_state["last_event_xml"][:5000], language="xml")
            st.caption("If teams show as 0 above, copy this and share it so the request/parser can be corrected.")

if "event" in st.session_state:
    ev = st.session_state["event"]
    teams = st.session_state["teams"]

    st.write(f"**{ev['name']}** ({ev['code']}) — {ev.get('start_main_draw')} to {ev.get('end_main_draw')}")
    default_event_date = ev.get("start_main_draw") or date.today()

    with st.container(border=True):
        st.subheader("Team status")
        status_counts = {}
        for t in teams:
            status_counts[t["draw_status"]] = status_counts.get(t["draw_status"], 0) + 1
        st.caption(
            "Status: 0=Normal (treated as Main Draw), 1=Deleted, 2=Withdrawn. "
            "Deleted/Withdrawn teams are excluded from the calculation by default."
        )
        cols = st.columns(len(status_counts) or 1)
        for col, (status, count) in zip(cols, status_counts.items()):
            col.metric(status, count)

        include_statuses = st.multiselect(
            "Include teams with these statuses in the calculation",
            options=list(status_counts.keys()),
            default=[s for s in status_counts if s == "Main Draw"],
        )

        with st.expander("Full team list with status"):
            st.dataframe([{
                "Team": t["name"], "NF": t.get("federation_code", ""),
                "Draw status": t["draw_status"], "Raw Status code": t["status_raw"],
                "Pos. Main Draw": t["position_in_main_draw"], "Pos. Reserve": t["position_in_reserve"],
            } for t in teams], use_container_width=True, hide_index=True)

    teams_for_calc = [t for t in teams if t["draw_status"] in include_statuses]
    if len(teams_for_calc) < len(teams):
        st.caption(f"{len(teams) - len(teams_for_calc)} team(s) excluded based on the status filter above.")

    with st.container(border=True):
        st.subheader("2. Cutoff dates")
        c1, c2 = st.columns(2)
        entry_cutoff = c1.date_input("Entry Point cutoff date", value=default_event_date - timedelta(days=35))
        seed_cutoff = c2.date_input("Seeding Point cutoff date", value=default_event_date - timedelta(days=1))

        if st.button("Calculate points for all teams", type="primary", disabled=not teams_for_calc):
            with st.spinner("Fetching player histories and scoring... this can take a while for large draws"):
                lookup = common_ui.load_tournament_lookup(client)
                avc_countries = common_ui.get_avc_country_codes(client)

                entry_main, entry_reserve = [], []
                seed_main, seed_reserve = [], []
                entry_breakdowns, seed_breakdowns = [], []

                for i, t in enumerate(teams_for_calc, start=1):
                    p1_career = common_ui.load_player_career(client, t["player1_no"], lookup)
                    p2_career = common_ui.load_player_career(client, t["player2_no"], lookup)

                    p1_entry = score_player(p1_career, entry_cutoff, template, avc_countries)
                    p2_entry = score_player(p2_career, entry_cutoff, template, avc_countries)
                    p1_seed = score_player(p1_career, seed_cutoff, template, avc_countries)
                    p2_seed = score_player(p2_career, seed_cutoff, template, avc_countries)

                    entry_row = TeamRow(
                        pos=i, nf=t.get("federation_code", ""), team_name=t["name"],
                        player1_name=t["player1_name"], player1_avc=p1_entry.avc_total,
                        player1_fivb=p1_entry.fivb_total, player2_name=t["player2_name"],
                        player2_avc=p2_entry.avc_total, player2_fivb=p2_entry.fivb_total,
                    )
                    seed_row = TeamRow(
                        pos=i, nf=t.get("federation_code", ""), team_name=t["name"],
                        player1_name=t["player1_name"], player1_avc=p1_seed.avc_total,
                        player1_fivb=p1_seed.fivb_total, player2_name=t["player2_name"],
                        player2_avc=p2_seed.avc_total, player2_fivb=p2_seed.fivb_total,
                    )
                    target_entry = entry_main if t["draw_status"] == "Main Draw" else entry_reserve
                    target_seed = seed_main if t["draw_status"] == "Main Draw" else seed_reserve
                    target_entry.append(entry_row)
                    target_seed.append(seed_row)

                    entry_breakdowns.append(PlayerBreakdown(t["player1_name"], t.get("federation_code", ""), p1_entry, template["fivb_side"]["max_events"]))
                    entry_breakdowns.append(PlayerBreakdown(t["player2_name"], t.get("federation_code", ""), p2_entry, template["fivb_side"]["max_events"]))
                    seed_breakdowns.append(PlayerBreakdown(t["player1_name"], t.get("federation_code", ""), p1_seed, template["fivb_side"]["max_events"]))
                    seed_breakdowns.append(PlayerBreakdown(t["player2_name"], t.get("federation_code", ""), p2_seed, template["fivb_side"]["max_events"]))

                st.session_state["entry_team_rows"] = entry_main
                st.session_state["entry_reserve_rows"] = entry_reserve
                st.session_state["seed_team_rows"] = seed_main
                st.session_state["seed_reserve_rows"] = seed_reserve
                st.session_state["entry_breakdowns"] = entry_breakdowns
                st.session_state["seed_breakdowns"] = seed_breakdowns
            st.success("Done!")

    if "entry_team_rows" in st.session_state:
        st.subheader("3. Results & export")

        logo_file = st.file_uploader("Optional: upload a logo to put on the Entry List sheet (PNG/JPG)",
                                      type=["png", "jpg", "jpeg"])
        logo_path = None
        if logo_file is not None:
            logo_path = str(pathlib.Path(tempfile.gettempdir()) / f"avc_logo_{logo_file.name}")
            with open(logo_path, "wb") as f:
                f.write(logo_file.getbuffer())

        tab1, tab2 = st.tabs(["🎯 Entry Points", "🌱 Seeding Points"])

        for tab, team_rows, reserve_rows, breakdowns, label in [
            (tab1, st.session_state["entry_team_rows"], st.session_state["entry_reserve_rows"], st.session_state["entry_breakdowns"], "Entry"),
            (tab2, st.session_state["seed_team_rows"], st.session_state["seed_reserve_rows"], st.session_state["seed_breakdowns"], "Seeding"),
        ]:
            with tab:
                sorted_rows = sorted(team_rows, key=lambda t: t.total, reverse=True)
                st.caption(f"Main Draw ({len(team_rows)} teams)")
                st.dataframe([{
                    "Pos": i + 1, "NF": t.nf, "Team": t.team_name,
                    "Player 1": t.player1_name, "P1 AVC": t.player1_avc, "P1 FIVB": t.player1_fivb,
                    "Player 2": t.player2_name, "P2 AVC": t.player2_avc, "P2 FIVB": t.player2_fivb,
                    "Total": t.total,
                } for i, t in enumerate(sorted_rows)], use_container_width=True, hide_index=True)

                if reserve_rows:
                    with st.expander(f"Reserve ({len(reserve_rows)} teams)"):
                        sorted_reserve = sorted(reserve_rows, key=lambda t: t.total, reverse=True)
                        st.dataframe([{
                            "Pos": i + 1, "NF": t.nf, "Team": t.team_name,
                            "Player 1": t.player1_name, "P1 AVC": t.player1_avc, "P1 FIVB": t.player1_fivb,
                            "Player 2": t.player2_name, "P2 AVC": t.player2_avc, "P2 FIVB": t.player2_fivb,
                            "Total": t.total,
                        } for i, t in enumerate(sorted_reserve)], use_container_width=True, hide_index=True)

                if st.button(f"Generate {label} Points Excel report", type="primary", key=f"gen_{label}"):
                    out_path = str(pathlib.Path(tempfile.gettempdir()) / f"{ev['code']}_{label}_points.xlsx")
                    build_workbook(
                        event_title=ev["name"],
                        event_subtitle=f"{ev.get('start_main_draw')} to {ev.get('end_main_draw')}",
                        gender_label="Women" if ev.get("gender") == "1" else "Men",
                        main_draw=team_rows, reserve=reserve_rows,
                        players=breakdowns,
                        output_path=out_path,
                        logo_path=logo_path,
                    )
                    with open(out_path, "rb") as f:
                        st.download_button(f"Download {label} Points report", f,
                                           file_name=f"{ev['code']}_{label}_points.xlsx", key=f"dl_{label}")
