"""
common_ui.py
------------
Shared look-and-feel + login gate + sidebar (scoring template) so Home.py
and pages/1_Calculator.py stay in sync and don't duplicate this logic.
Streamlit keeps one shared st.session_state across pages in the same
browser session, so logging in / picking a template on one page carries
over to the other automatically.
"""

from datetime import date, timedelta

import streamlit as st

import templates as tpl_store
from vis_client import VisClient
from vis_parser import parse_tournament_list, parse_player_career

AVC_BLUE = "#0B3D91"
AVC_GOLD = "#F2A900"


def inject_style():
    st.markdown(
        f"""
        <style>
        .stApp {{ background-color: #f7f9fc; }}
        h1, h2, h3 {{ color: {AVC_BLUE}; }}
        div[data-testid="stMetric"] {{
            background-color: white;
            border: 1px solid #e3e8f0;
            border-radius: 10px;
            padding: 12px 16px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        div[data-testid="stMetricValue"] {{ color: {AVC_BLUE}; }}
        section[data-testid="stSidebar"] {{ background-color: #ffffff; }}
        div[data-testid="stDataFrame"] {{ border-radius: 8px; overflow: hidden; }}
        .stButton > button[kind="primary"] {{ background-color: {AVC_BLUE}; }}
        .avc-login-title {{ color: {AVC_BLUE}; font-weight: 700; font-size: 1.1em; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def most_recent_monday(today: date = None) -> date:
    today = today or date.today()
    return today - timedelta(days=today.weekday())  # Monday == 0


# ---------------------------------------------------------------------
# Login gate (st.dialog modal) - required before any page shows its content
# ---------------------------------------------------------------------

@st.dialog("Log in to FIVB VIS")
def _login_dialog():
    st.markdown('<span class="avc-login-title">🏐 AVC Points Calculator</span>', unsafe_allow_html=True)
    st.caption("Enter your FIVB VIS credentials to continue.")
    username = st.text_input("Username", key="login_username_field")
    password = st.text_input("Password", type="password", key="login_password_field")
    if st.button("Log in", type="primary", use_container_width=True):
        if not username or not password:
            st.error("Enter both a username and password.")
        else:
            client = VisClient(username, password)
            try:
                with st.spinner("Checking credentials..."):
                    ok = client.test_connection()
                if ok:
                    st.session_state["vis_username"] = username
                    st.session_state["vis_password"] = password
                    st.session_state["vis_authenticated"] = True
                    st.rerun()
                else:
                    st.error("Got an unexpected response from VIS - double-check your credentials.")
            except Exception as e:
                st.error(f"Login failed: {e}")


def require_login() -> VisClient:
    """Call at the very top of every page. Blocks (via a modal + st.stop())
    until VIS credentials are verified, then returns a ready-to-use client."""
    if not st.session_state.get("vis_authenticated"):
        _login_dialog()
        st.stop()
    return VisClient(st.session_state["vis_username"], st.session_state["vis_password"])


def render_sidebar():
    """Renders the logged-in indicator + scoring template controls in the
    sidebar and returns the active template dict."""
    st.sidebar.success(f"Logged in as **{st.session_state.get('vis_username', '')}**")
    if st.sidebar.button("Log out"):
        for k in ("vis_authenticated", "vis_username", "vis_password"):
            st.session_state.pop(k, None)
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.subheader("Scoring template")
    all_templates = tpl_store.load_all()
    template_name = st.sidebar.selectbox("Template", list(all_templates.keys()), key="template_name")
    template = all_templates[template_name]

    with st.sidebar.expander("Edit / create template"):
        with st.form("template_form"):
            t_name = st.text_input("Template name", value=template_name)
            lookback = st.number_input("Lookback window (days)", value=template.get("lookback_days", 365))
            fivb_max = st.number_input("FIVB side: max events counted", value=template["fivb_side"]["max_events"], min_value=1, max_value=10)
            avc_max = st.number_input("AVC side: max events counted", value=template["avc_side"]["max_events"], min_value=1, max_value=10)
            ms_cap = st.number_input(
                "Cap on Multi-sport/Zonal (TOTAL across both sides combined)",
                value=(template.get("global_cap_groups", [{}])[0].get("limit", 1)
                       if template.get("global_cap_groups") else 1),
                min_value=0, max_value=10,
            )
            champ_cap = st.number_input("AVC side: cap on Continental Championship", value=template["avc_side"]["caps"].get("championship", 1), min_value=0, max_value=10)
            submitted = st.form_submit_button("Save template")
            if submitted:
                new_t = tpl_store.make_template(t_name, lookback, fivb_max, avc_max, ms_cap, champ_cap)
                tpl_store.save_template(new_t)
                st.success(f"Saved template '{t_name}'. Reload the page to select it.")

    return template


# ---------------------------------------------------------------------
# Shared data-loading helpers (used by both Home.py and the Calculator page)
# ---------------------------------------------------------------------

def load_tournament_lookup(client):
    """code -> {no, type, organizer_code, country_code, ...}. Cached in
    session_state for the whole session (shared across pages) since it's
    the full multi-thousand-row list."""
    if "tournament_lookup" in st.session_state:
        return st.session_state["tournament_lookup"]
    this_year = date.today().year
    xml = client.get_tournament_list(this_year - 3, this_year + 1)
    tournaments = parse_tournament_list(xml)
    lookup = {t["code"]: t for t in tournaments}
    st.session_state["tournament_lookup"] = lookup
    return lookup


def load_player_career(client, player_no: str, tournament_lookup: dict):
    """Fetch + classify-merge one player's full career. Cached per player
    number for the session so re-scoring at a different cutoff date (or
    on a different page) doesn't re-hit VIS."""
    cache = st.session_state.setdefault("career_cache", {})
    if player_no not in cache:
        xml = client.get_player_career(player_no)
        career = parse_player_career(xml, player_no)
        for r in career:
            t = tournament_lookup.get(r.tournament_code)
            if t:
                r.organizer_code = t["organizer_code"]
                if not r.country_code:
                    r.country_code = t["country_code"]
        cache[player_no] = career
    return _with_manual(player_no, cache[player_no])


def _with_manual(player_no: str, career: list) -> list:
    """Career + results added from Final Ranking PDFs (kept outside the cache so
    they can be added/removed any time). Skipped once VIS has the event itself."""
    extra = [ev["results"][player_no] for ev in st.session_state.get("manual_events", {}).values()
             if player_no in ev["results"]]
    if not extra:
        return career
    have = {r.tournament_code for r in career}
    return career + [r for r in extra if r.tournament_code not in have]


def render_manual_results(client, teams: list, key: str):
    """Expander: upload VIS 'Final Ranking' PDF(s) of events VIS has not yet
    credited to the players; points = team points / 2 per player. Shared between
    pages via st.session_state['manual_events']."""
    from manual_results import parse_ranking_pdf, match_rows, build_results
    events = st.session_state.setdefault("manual_events", {})
    with st.expander(f"➕ Add points from a Final Ranking PDF (event not yet in VIS)"
                     + (f" — {len(events)} added" if events else "")):
        st.caption("Upload the VIS 'Final Ranking - Main draw' PDF. Team points are split 50/50 between "
                   "the two players. Players are matched by name inside the teams of the entry list "
                   "loaded above; check the table, then add. After adding, press Calculate again. "
                   "Once VIS credits the event itself, the VIS result is used and this one is ignored.")
        for k, ev in list(events.items()):
            c1, c2 = st.columns([5, 1])
            c1.write(f"✅ **{ev['label']}** — {len(ev['results'])} players")
            if c2.button("Remove", key=f"{key}_rm_{k}"):
                events.pop(k)
                st.rerun()

        pdf = st.file_uploader("Final Ranking PDF", type=["pdf"], key=f"{key}_pdf")
        if pdf is None:
            return
        try:
            rep = parse_ranking_pdf(pdf)
        except Exception as e:
            st.error(str(e))
            return

        lookup = load_tournament_lookup(client)
        cands = []
        for t in teams:
            pair = (t["player1_no"], t["player2_no"])
            for no, nm in ((t["player1_no"], t["player1_name"]), (t["player2_no"], t["player2_name"])):
                cands.append({"no": no, "name": nm, "nf": t.get("federation_code", ""),
                              "team": t["name"], "pair": pair})
        names = {c["no"]: c["name"] for c in cands}

        gcode = "1" if rep.gender == "Women" else "0"
        opts = [t for t in lookup.values()
                if t["end_main_draw"] and rep.end_date and abs((t["end_main_draw"] - rep.end_date).days) <= 120]
        opts.sort(key=lambda t: (
            0 if (t["name"].strip().lower() == rep.event_name.strip().lower() and t["gender"] == gcode) else 1,
            abs((t["end_main_draw"] - rep.end_date).days)))
        if not opts:
            st.error("Could not find this event in the VIS tournament list - load the list first.")
            return
        tour = st.selectbox("Event in VIS (gives type / organiser / date)", opts, key=f"{key}_tour_{pdf.file_id}",
                            format_func=lambda t: f"{t['code']} — {t['name']} "
                                                  f"({'W' if t['gender']=='1' else 'M'}, {t['end_main_draw']})")
        st.write(f"**{rep.event_name} / {rep.gender}** — ended {rep.end_date}, {len(rep.rows)} teams")

        matches = match_rows(rep.rows, cands)
        labels = {"": ""}
        labels.update({c["no"]: f"{c['nf']} | {c['name']}" for c in cands})
        rows = [{"Rk": m["row"].rank, "PDF team": m["row"].team, "Country": m["row"].country,
                 "Name in PDF": m["half"], "Player": labels.get(m["player_no"], ""),
                 "Team pts": m["row"].points, "Player pts": m["row"].points / 2}
                for m in matches]
        inv = {v: k for k, v in labels.items()}
        ed = st.data_editor(
            rows, hide_index=True, use_container_width=True, key=f"{key}_tbl_{pdf.file_id}",
            disabled=["Rk", "PDF team", "Country", "Name in PDF", "Team pts"],
            column_config={
                "Player": st.column_config.SelectboxColumn("Player (entry list)", options=list(labels.values())),
                "Player pts": st.column_config.NumberColumn("Player pts (team ÷ 2)", step=1),
            })
        ed = ed if isinstance(ed, list) else ed.to_dict("records")
        n_ok = sum(1 for r in ed if r["Player"])
        st.caption(f"{n_ok} of {len(ed)} names matched to players in this entry list. "
                   "Unmatched names are simply not counted (those players are not in this event).")

        if st.button("Add these points", type="primary", key=f"{key}_add_{pdf.file_id}", disabled=n_ok == 0):
            for m, r in zip(matches, ed):
                m["player_no"] = inv.get(r["Player"], "")
                m["pts"] = r["Player pts"]
            res = build_results(
                matches, names, code=tour["code"], name=tour["name"], season=tour["season"],
                end_date=tour["end_main_draw"], tournament_type=tour["type"],
                organizer_code=tour["organizer_code"], host_country=tour["country_code"],
                points_for=lambda m: round(m["pts"]))
            events[f"{tour['code']}_{rep.gender}"] = {
                "label": f"{tour['name']} ({rep.gender}, {tour['end_main_draw']})", "results": res}
            st.rerun()


def get_avc_country_codes(client):
    if "avc_country_codes" not in st.session_state:
        st.session_state["avc_country_codes"] = client.get_avc_country_codes()
    return st.session_state["avc_country_codes"]
