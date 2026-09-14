"""
Home.py - landing page (also the login entry point).

Run with:  streamlit run Home.py
"""

import streamlit as st

import common_ui

st.set_page_config(page_title="AVC Points Calculator", page_icon="🏐", layout="wide")
common_ui.inject_style()

client = common_ui.require_login()  # blocks with a login modal until VIS creds are verified
template = common_ui.render_sidebar()

st.title("🏐 AVC Beach Volleyball — Entry / Seeding Points Tool")

c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("### 1️⃣ Pick a tournament")
    st.write("Choose from a live list of AVC-organised events, or enter a code/number directly.")
with c2:
    st.markdown("### 2️⃣ Set cutoff dates")
    st.write("Entry Point and Seeding Point cutoffs default to −35 / −1 days, fully editable.")
with c3:
    st.markdown("### 3️⃣ Export the report")
    st.write("Get every team's points and download the Entry List + Breakdown Excel file.")

st.divider()
st.info("👈 Open **1 🧮 Calculator** in the sidebar to get started.")

with st.expander("Active scoring template"):
    st.json(template)
