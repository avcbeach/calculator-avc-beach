"""
hub_ui.py
---------
"Pick the event from Beach Hub" widget, shared by the Calculator and Signing Sheet pages.
The chosen Hub event gives the VIS tournament number; events not linked to VIS yet can be
linked right here (candidates come from the VIS tournament list by date).
"""

from datetime import date

import streamlit as st

import common_ui
import hub_client


def source_choice(key: str) -> str:
    """'hub' or 'vis'. Shows the switch only when the Hub is set up."""
    if not hub_client.config():
        return "vis"
    pick = st.radio("Pick the tournament from", ["Beach Hub events", "VIS tournament list"],
                    horizontal=True, key=f"{key}_src")
    return "hub" if pick.startswith("Beach Hub") else "vis"


def hub_picker(client, key: str):
    """Returns a VIS tournament No (str) for the chosen Hub event, or None."""
    try:
        evs = hub_client.events(include_fivb=st.checkbox("Include FIVB events", key=f"{key}_fivb"))
    except Exception as e:
        st.error(f"Could not load events from Beach Hub: {e}")
        return None
    if not evs:
        st.warning("No events in Beach Hub yet - add them on the Hub's Events page.")
        return None

    today = date.today()
    evs = sorted(evs, key=lambda e: e["start"] or date.min, reverse=True)
    # default: the running event, else the next one, else the latest
    upcoming = [e for e in evs if e["end"] and e["end"] >= today]
    default = upcoming[-1] if upcoming else evs[0]
    ev = st.selectbox("Event (Beach Hub)", evs, index=evs.index(default), key=f"{key}_hub_event",
                      format_func=lambda e: hub_client.label(e) + ("" if e["vis_nos"] else "  ·  not linked to VIS"))

    if not ev["vis_nos"]:
        _link_to_vis(client, ev, key)
        return None

    nos = ev["vis_nos"]
    by_no = {t["no"]: t for t in st.session_state.get("tournament_lookup", {}).values()}

    def nice(no):
        t = by_no.get(no)
        if not t:
            return f"VIS No {no}"
        g = {"0": "Men", "1": "Women"}.get(t["gender"], "")
        return f"{g} — {t['code']} (VIS No {no})" if g else f"{t['code']} (VIS No {no})"

    if len(nos) == 1:
        st.caption(f"Linked to {nice(nos[0])}")
        return nos[0]
    return st.radio("Which tournament?", nos, format_func=nice, horizontal=True, key=f"{key}_hub_no")


def _link_to_vis(client, ev: dict, key: str):
    st.info("This event is not linked to a VIS tournament yet. Find it below and save the link to Beach Hub - "
            "every app will then use it.")
    if "tournament_lookup" not in st.session_state:
        if st.button("Find it in the VIS tournament list", key=f"{key}_find"):
            with st.spinner("Fetching tournament list from VIS (can take a moment)..."):
                common_ui.load_tournament_lookup(client)
            st.rerun()
        return

    lookup = st.session_state["tournament_lookup"]
    s = ev["start"]
    if not s:
        st.warning("This event has no start date in Beach Hub.")
        return
    near = [t for t in lookup.values() if t["start_main_draw"] and abs((t["start_main_draw"] - s).days) <= 7]
    near.sort(key=lambda t: (t["organizer_code"] != "AVC", abs((t["start_main_draw"] - s).days), t["gender"]))
    if not near:
        st.warning("No VIS tournament starts within a week of this event's dates. Check the dates in Beach Hub, "
                   "or enter the VIS No manually below.")
        return

    def nice(t):
        g = {"0": "Men", "1": "Women"}.get(t["gender"], "")
        return f"{t['code']} — {t['name']} · {g} · {t['country_code']} · {t['start_main_draw']} (No {t['no']})"

    same_day = [t for t in near if t["start_main_draw"] == s and t["organizer_code"] == "AVC"]
    picked = st.multiselect("VIS tournament(s) for this event - pick Men and Women if both", near,
                            default=same_day[:2], format_func=nice, key=f"{key}_link_pick")
    if st.button("Save link to Beach Hub", type="primary", disabled=not picked, key=f"{key}_link_save"):
        try:
            hub_client.set_vis_no(ev["event_id"], [t["no"] for t in picked])
            st.success("Saved - every Hub app now knows this event's VIS number(s).")
            st.rerun()
        except Exception as e:
            st.error(str(e))
