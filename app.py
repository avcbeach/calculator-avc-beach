"""
app.py - AVC Entry/Seeding Points Calculator (Streamlit)

Run with:  streamlit run app.py

Two modes:
  - "Demo (sample files)": uses the 3 sample VIS responses you already
    provided, in data/. Lets you sanity-check the scoring logic and the
    exported Excel layout with zero setup - start here.
  - "Live VIS": calls the real FIVB VIS API with your credentials.
    NOTE: the auth style (Basic vs embedded) is a best guess - use
    "Test connection" first. See vis_client.py for details.
"""

import io
import re
import tempfile
import pathlib
from datetime import date, timedelta

import streamlit as st

from classification import DEFAULT_TEMPLATE
from scoring_engine import score_player, CareerResult
from vis_parser import parse_player_career, parse_tournament_list, parse_tournament_entry_list
from vis_client import VisClient
from excel_export import build_workbook, TeamRow, PlayerBreakdown
import templates as tpl_store

st.set_page_config(page_title="AVC Points Calculator", layout="wide")
st.title("AVC Beach Volleyball — Entry / Seeding Points Calculator")

# ---------------------------------------------------------------------
# Sidebar: mode + template
# ---------------------------------------------------------------------
mode = st.sidebar.radio("Data source", ["Demo (sample files)", "Live VIS"])

st.sidebar.markdown("---")
st.sidebar.subheader("Scoring template")
all_templates = tpl_store.load_all()
template_name = st.sidebar.selectbox("Template", list(all_templates.keys()))
template = all_templates[template_name]

with st.sidebar.expander("Edit / create template"):
    with st.form("template_form"):
        t_name = st.text_input("Template name", value=template_name)
        lookback = st.number_input("Lookback window (days)", value=template.get("lookback_days", 365))
        fivb_max = st.number_input("FIVB side: max events counted", value=template["fivb_side"]["max_events"], min_value=1, max_value=10)
        avc_max = st.number_input("AVC side: max events counted", value=template["avc_side"]["max_events"], min_value=1, max_value=10)
        ms_cap = st.number_input("Cap on Multi-sport/Zonal (TOTAL across both sides combined)", value=template.get("global_cap_groups", [{}])[0].get("limit", 1) if template.get("global_cap_groups") else 1, min_value=0, max_value=10)
        champ_cap = st.number_input("AVC side: cap on Continental Championship", value=template["avc_side"]["caps"].get("championship", 1), min_value=0, max_value=10)
        submitted = st.form_submit_button("Save template")
        if submitted:
            new_t = tpl_store.make_template(t_name, lookback, fivb_max, avc_max, ms_cap, champ_cap)
            tpl_store.save_template(new_t)
            st.success(f"Saved template '{t_name}'. Reload the page to select it.")

st.sidebar.markdown("---")
if mode == "Live VIS":
    st.sidebar.subheader("VIS credentials")
    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")
    auth_style = st.sidebar.selectbox("Auth style", ["basic", "embedded"])
    if st.sidebar.button("Test connection"):
        try:
            client = VisClient(username, password, auth_style=auth_style)
            ok = client.test_connection()
            st.sidebar.success("Connected!" if ok else "Got a response, but it looked unexpected - check the raw XML.")
        except Exception as e:
            st.sidebar.error(f"Connection failed: {e}")

# ---------------------------------------------------------------------
# Data-loading helpers (defined before use since Streamlit runs top-to-
# bottom like a script)
# ---------------------------------------------------------------------

def load_tournament_lookup():
    """code -> {no, type, organizer_code, country_code} for classification
    merges AND for resolving a Code to the numeric No that GetBeachTournament
    requires. Cached in session_state so we only fetch this once per run
    (it's the full multi-thousand-row list in Live mode)."""
    if "tournament_lookup" in st.session_state:
        return st.session_state["tournament_lookup"]
    if mode == "Demo (sample files)":
        with open("data/Responses_tournament_list.txt", encoding="utf-8") as f:
            xml = f.read()
    else:
        client = VisClient(username, password, auth_style=auth_style)
        this_year = date.today().year
        xml = client.get_tournament_list(this_year - 3, this_year + 1)
    tournaments = parse_tournament_list(xml)
    lookup = {t["code"]: t for t in tournaments}
    st.session_state["tournament_lookup"] = lookup
    return lookup


def load_event():
    if mode == "Demo (sample files)":
        with open("data/Responses_event.txt", encoding="utf-8") as f:
            xml = f.read()
    else:
        client = VisClient(username, password, auth_style=auth_style)
        value = tournament_code_or_no.strip()
        if not value.isdigit():
            # user gave a Code like "MAG2026" - resolve it to the numeric No
            # that GetBeachTournament actually requires.
            lookup = load_tournament_lookup()
            match = lookup.get(value.upper()) or lookup.get(value)
            if not match or not match.get("no"):
                raise ValueError(
                    f"Could not find tournament code '{value}' in the tournament "
                    f"list to resolve its numeric No. Double-check the code, or "
                    f"enter the numeric No directly if you have it."
                )
            value = match["no"]
        xml = client.get_tournament_entry_list(value)
    st.session_state["last_event_xml"] = xml  # for the debug expander below
    return parse_tournament_entry_list(xml)


def load_player_career(player_no: str, lookup: dict):
    if mode == "Demo (sample files)":
        with open("data/Responses.txt", encoding="utf-8") as f:
            xml = f.read()
    else:
        client = VisClient(username, password, auth_style=auth_style)
        xml = client.get_player_career(player_no)
    career = parse_player_career(xml, player_no)
    for r in career:
        t = lookup.get(r.tournament_code)
        if t:
            r.organizer_code = t["organizer_code"]
            if not r.country_code:
                r.country_code = t["country_code"]
    return career


def get_avc_country_codes():
    if mode == "Demo (sample files)":
        # sample player/tournament dumps don't include a federation list;
        # fall back to an empty set (multi-sport games will default to the
        # "FIVB, not hosted in AVC" bucket unless OrganizerCode == AVC).
        return set()
    client = VisClient(username, password, auth_style=auth_style)
    return client.get_avc_country_codes()


# ---------------------------------------------------------------------
# Main: event selection
# ---------------------------------------------------------------------
def _season_year(season_str) -> int:
    """Seasons are usually a plain year ('2026') but some old records use a
    split-season format like '1991-92' - just take the first 4-digit year
    found, or 0 if nothing parses."""
    m = re.search(r"\d{4}", str(season_str or ""))
    return int(m.group()) if m else 0


st.header("1. Select tournament")

if mode == "Demo (sample files)":
    st.info("Using the bundled sample files (data/Responses_event.txt, data/Responses.txt, "
            "data/Responses_tournament_list.txt). Good for checking the calculation logic and "
            "report layout before you point this at live VIS.")
    tournament_code_or_no = "MAG2026"  # demo mode always loads the sample event regardless
    st.text_input("Tournament (fixed in demo mode)", value=tournament_code_or_no, disabled=True)
else:
    year_now = date.today().year
    c1, c2, c3 = st.columns([1, 1, 2])
    season_from = c1.number_input("From season", value=year_now - 1, step=1)
    season_to = c2.number_input("To season", value=year_now + 1, step=1)
    avc_only = c3.checkbox("AVC-organised events only", value=True)

    if st.button("Load tournament list"):
        with st.spinner("Fetching tournament list from VIS (this pulls the full list, can take a moment)..."):
            lookup = load_tournament_lookup()
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
                start = t["start_main_draw"]
                return f"{t['code']} — {t['name']} ({start})"

            choice = st.selectbox("Tournament", options, format_func=_label)
            tournament_code_or_no = choice["code"]
        else:
            st.warning("No tournaments match this filter - try widening the season range or unchecking 'AVC-organised only'.")

    with st.expander("Or enter a tournament Code / No manually"):
        manual = st.text_input("Tournament No or Code")
        if manual:
            tournament_code_or_no = manual



if st.button("Load entry list", disabled=not tournament_code_or_no):
    try:
        with st.spinner("Loading..."):
            parsed = load_event()
            st.session_state["event"] = parsed["event"]
            st.session_state["teams"] = parsed["teams"]
        st.success(f"Loaded {parsed['event']['name']} — {len(parsed['teams'])} teams")
    except Exception as e:
        st.error(str(e))

if "last_event_xml" in st.session_state:
    with st.expander("Debug: raw VIS response for the last 'Load entry list' call"):
        st.code(st.session_state["last_event_xml"][:5000], language="xml")
        st.caption("If teams show as 0 above, copy this (or the first part of it) "
                   "and share it so the request/parser can be corrected.")

if "event" in st.session_state:
    ev = st.session_state["event"]
    teams = st.session_state["teams"]

    st.write(f"**{ev['name']}** ({ev['code']}) — {ev.get('start_main_draw')} to {ev.get('end_main_draw')}")

    default_event_date = ev.get("start_main_draw") or date.today()

    st.header("2. Cutoff dates")
    c1, c2 = st.columns(2)
    entry_cutoff = c1.date_input("Entry Point cutoff date", value=default_event_date - timedelta(days=35))
    seed_cutoff = c2.date_input("Seeding Point cutoff date", value=default_event_date - timedelta(days=1))

    if st.button("Calculate points for all teams"):
        with st.spinner("Fetching player histories and scoring... this can take a while for large draws"):
            lookup = load_tournament_lookup()
            avc_countries = get_avc_country_codes()

            entry_team_rows = []
            seed_team_rows = []
            entry_breakdowns = []
            seed_breakdowns = []

            # cache player careers so we don't re-fetch a player who appears twice
            career_cache = {}

            def get_career(no):
                if no not in career_cache:
                    career_cache[no] = load_player_career(no, lookup)
                return career_cache[no]

            for i, t in enumerate(teams, start=1):
                p1_career = get_career(t["player1_no"])
                p2_career = get_career(t["player2_no"])

                p1_entry = score_player(p1_career, entry_cutoff, template, avc_countries)
                p2_entry = score_player(p2_career, entry_cutoff, template, avc_countries)
                p1_seed = score_player(p1_career, seed_cutoff, template, avc_countries)
                p2_seed = score_player(p2_career, seed_cutoff, template, avc_countries)

                entry_team_rows.append(TeamRow(
                    pos=i, nf=t.get("federation_code", ""), team_name=t["name"],
                    player1_name=t["player1_name"], player1_avc=p1_entry.avc_total,
                    player1_fivb=p1_entry.fivb_total, player2_name=t["player2_name"],
                    player2_avc=p2_entry.avc_total, player2_fivb=p2_entry.fivb_total,
                ))
                seed_team_rows.append(TeamRow(
                    pos=i, nf=t.get("federation_code", ""), team_name=t["name"],
                    player1_name=t["player1_name"], player1_avc=p1_seed.avc_total,
                    player1_fivb=p1_seed.fivb_total, player2_name=t["player2_name"],
                    player2_avc=p2_seed.avc_total, player2_fivb=p2_seed.fivb_total,
                ))
                entry_breakdowns.append(PlayerBreakdown(t["player1_name"], t.get("federation_code", ""), p1_entry, template["fivb_side"]["max_events"]))
                entry_breakdowns.append(PlayerBreakdown(t["player2_name"], t.get("federation_code", ""), p2_entry, template["fivb_side"]["max_events"]))
                seed_breakdowns.append(PlayerBreakdown(t["player1_name"], t.get("federation_code", ""), p1_seed, template["fivb_side"]["max_events"]))
                seed_breakdowns.append(PlayerBreakdown(t["player2_name"], t.get("federation_code", ""), p2_seed, template["fivb_side"]["max_events"]))

            st.session_state["entry_team_rows"] = entry_team_rows
            st.session_state["seed_team_rows"] = seed_team_rows
            st.session_state["entry_breakdowns"] = entry_breakdowns
            st.session_state["seed_breakdowns"] = seed_breakdowns

        st.success("Done!")

    if "entry_team_rows" in st.session_state:
        st.header("3. Results & export")
        tab1, tab2 = st.tabs(["Entry Points", "Seeding Points"])

        for tab, team_rows, breakdowns, label in [
            (tab1, st.session_state["entry_team_rows"], st.session_state["entry_breakdowns"], "Entry"),
            (tab2, st.session_state["seed_team_rows"], st.session_state["seed_breakdowns"], "Seeding"),
        ]:
            with tab:
                sorted_rows = sorted(team_rows, key=lambda t: t.total, reverse=True)
                st.dataframe([{
                    "Pos": i + 1, "NF": t.nf, "Team": t.team_name,
                    "Player 1": t.player1_name, "P1 AVC": t.player1_avc, "P1 FIVB": t.player1_fivb,
                    "Player 2": t.player2_name, "P2 AVC": t.player2_avc, "P2 FIVB": t.player2_fivb,
                    "Total": t.total,
                } for i, t in enumerate(sorted_rows)])

                if st.button(f"Generate {label} Points Excel report", key=f"gen_{label}"):
                    out_path = str(pathlib.Path(tempfile.gettempdir()) / f"{ev['code']}_{label}_points.xlsx")
                    build_workbook(
                        event_title=ev["name"],
                        event_subtitle=f"{ev.get('start_main_draw')} to {ev.get('end_main_draw')}",
                        gender_label="Women" if ev.get("gender") == "1" else "Men",
                        main_draw=team_rows, reserve=[],
                        players=breakdowns,
                        output_path=out_path,
                    )
                    with open(out_path, "rb") as f:
                        st.download_button(f"Download {label} Points report", f, file_name=f"{ev['code']}_{label}_points.xlsx", key=f"dl_{label}")
