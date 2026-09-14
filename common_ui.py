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
    return cache[player_no]


def get_avc_country_codes(client):
    if "avc_country_codes" not in st.session_state:
        st.session_state["avc_country_codes"] = client.get_avc_country_codes()
    return st.session_state["avc_country_codes"]
