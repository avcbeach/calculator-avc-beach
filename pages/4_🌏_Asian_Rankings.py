"""
pages/4_Asian_Rankings.py - Asian (AVC) team ranking at a chosen date, scored with the
same rules as the Entry / Seeding points (template in the sidebar).

How it works: every event that ended inside the lookback window is scanned for its
Main Draw teams; players of AVC federations are collected, their careers are loaded and
scored, every pair that played together in the window becomes a team (a player with two
partners appears in two pairs), and teams are ranked by the sum of both players' points.
"""

import tempfile
import pathlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import streamlit as st

import common_ui
from classification import classify_tournament
from vis_parser import parse_tournament_entry_list
from asian_rankings import collect_candidates, all_pairs, rank_teams
from ranking_export import build_ranking_workbook
from public_site import (new_site, add_ranking, ranking_to_dict, extract_site, build_site_html, build_explainer_html)

st.set_page_config(page_title="Asian Rankings", page_icon="🌏", layout="wide")
common_ui.inject_style()

client = common_ui.require_login()
template = common_ui.render_sidebar()

st.title("🌏 Asian Rankings")
st.caption("Current team ranking of all AVC federations, scored with the same rules as the Entry / Seeding "
           "points (AVC + FIVB points of both players, template from the sidebar). Teams of other "
           "confederations are not listed.")

common_ui.load_disk_cache()

with st.container(border=True):
    st.subheader("1. Settings")
    c1, c2 = st.columns(2)
    rank_date = c1.date_input("Ranking date (cutoff)", value=date.today(), key="rk_date")
    lookback = template.get("lookback_days", 365)
    c2.metric("Lookback window", f"{lookback} days", help="From the scoring template in the sidebar.")
    min_pts = st.number_input("Hide teams with fewer total points than", value=1, min_value=0, step=1, key="rk_min")
    method = st.radio("Ranking method",
                      ["By pair - only points the two earned together (like the FIVB team ranking)",
                       "By players - each player's whole record, added together"],
                      key="rk_method")
    st.caption("By pair: a player who played with two partners appears in two pairs, each with its own points. "
               "The same best-N / cap rules of the template apply to each pair's own results.")
    logo_file = st.file_uploader("Optional: logo for the Excel file (PNG/JPG)", type=["png", "jpg", "jpeg"], key="rk_logo")
    st.caption("The first run scans every event of the last year and loads each player's history from VIS, "
               "so it can take several minutes. Histories are kept for the rest of the session, so later runs "
               "(or other pages) are much faster.")
    saved = st.session_state.get("disk_cache_info")
    if saved:
        import time as _t
        cc1, cc2 = st.columns([4, 1])
        cc1.caption(f"✅ Using downloaded VIS data saved at {_t.strftime('%d %b %H:%M', _t.localtime(saved))} "
                    f"({len(st.session_state.get('career_cache', {}))} players, kept up to "
                    f"{common_ui.CACHE_MAX_AGE_H} h). Clear it to download everything again.")
        if cc2.button("Clear saved data", key="rk_clear"):
            common_ui.clear_disk_cache()
            st.rerun()
    go = st.button("Build rankings", type="primary", key="rk_go")


def _gh_config():
    """(token, repo, branch) from Streamlit secrets [github], or None when not set up."""
    try:
        g = st.secrets["github"]
        return g["token"], g["repo"], g.get("branch", "main")
    except Exception:
        return None


def _pg_config():
    """(url, key) from Streamlit secrets [playground] (AVC's own server), or None."""
    try:
        g = st.secrets["playground"]
        return str(g["url"]).strip(), str(g["key"]).strip()
    except Exception:
        return None


def _can_publish():
    return bool(_pg_config() or _gh_config())


def _site_with(res, site, title, name, rid_raw, desc, logo_file):
    """Add this ranking to `site` (a dict from extract_site, or None for a new page)."""
    import base64, re as _re
    site = site or new_site(title)
    site["title"] = title
    if logo_file is not None:
        mime = "image/png" if logo_file.name.lower().endswith("png") else "image/jpeg"
        site["logo"] = f"data:{mime};base64," + base64.b64encode(logo_file.getvalue()).decode()
    rid = _re.sub(r"[^a-z0-9-]+", "-", rid_raw.strip().lower()).strip("-") or "ranking"
    add_ranking(site, ranking_to_dict(rid, name.strip() or rid, res["rows"], res["date"], desc.strip(),
                                         mode=res.get("mode", "player"), template=template,
                                         min_points=int(res.get("min_pts", 0))))
    return site


def _publish_to_github(res):
    """Refresh the live page: read index.html from the repo (keeps its other rankings), add this
    ranking, write index.html + how-it-works.html back. Returns a message for the user."""
    pg, cfg = _pg_config(), _gh_config()
    if not pg and not cfg:
        return None
    if pg:   # AVC's own server (playground) — preferred when set up
        import site_publish as sp
        old = sp.read_file(pg[0], pg[1], "index.html")
    else:
        import github_publish as gh
        token, repo, branch = cfg
        old, _ = gh.read_file(repo, "index.html", branch, token)
    site = extract_site(old) if old else None
    ss = st.session_state
    site = _site_with(res, site, ss.get("rk_pub_title", "AVC Beach Volleyball Rankings"),
                      ss.get("rk_pub_name", "Asian Rankings"), ss.get("rk_pub_id", "asian-rankings"),
                      ss.get("rk_pub_desc", ""), ss.get("rk_logo"))
    msg = f"Rankings as of {res['date']:%d %b %Y}"
    if pg:
        a = sp.write_file(pg[0], pg[1], "index.html", build_site_html(site))
        b = sp.write_file(pg[0], pg[1], "how-it-works.html", build_explainer_html(site))
    else:
        a = gh.write_file(repo, "index.html", branch, token, build_site_html(site), msg)
        b = gh.write_file(repo, "how-it-works.html", branch, token, build_explainer_html(site), msg)
    return "published" if (a or b) else "unchanged"


def _fetch_teams(no):
    return no, parse_tournament_entry_list(client.get_tournament_entry_list(no))["teams"]


if go:
    try:
        lookup = common_ui.load_tournament_lookup(client)
        avc_countries = common_ui.get_avc_country_codes(client)
        avc_feds = common_ui.get_avc_federation_codes(client)
        if not avc_feds:
            raise RuntimeError("VIS returned no AVC federations.")

        from datetime import timedelta
        start = rank_date - timedelta(days=lookback)
        events = []
        for t in lookup.values():
            if not t["end_main_draw"] or not (start <= t["end_main_draw"] <= rank_date) or not t["no"]:
                continue
            cls = classify_tournament(t["type"], t["organizer_code"], t["country_code"], avc_countries)
            if cls.side in ("FIVB", "AVC"):
                events.append(t)
        if not events:
            raise RuntimeError("No events found in the window - load the tournament list on the Calculator page first.")

        team_cache = st.session_state.setdefault("rk_team_cache", {})
        todo = [t for t in events if t["no"] not in team_cache]
        bar = st.progress(0.0, text=f"Scanning {len(events)} events for players...")
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(_fetch_teams, t["no"]) for t in todo]
            for i, f in enumerate(as_completed(futs), start=1):
                try:
                    no, teams = f.result()
                    team_cache[no] = teams
                except Exception:
                    pass      # an unreadable event only means fewer candidate players
                bar.progress(i / max(len(futs), 1), text=f"Scanning events {i}/{len(futs)}")
        scanned = [(t, team_cache[t["no"]]) for t in events if t["no"] in team_cache]
        cands = collect_candidates(scanned, avc_feds)

        bar2 = st.progress(0.0, text=f"Loading histories of {len(cands)} players...")
        common_ui.save_disk_cache()        # scanned events are saved too
        common_ui.load_careers_bulk(client, list(cands), lookup,
                                    progress=lambda d, n: bar2.progress(d / max(n, 1), text=f"Players {d}/{n}"))
        cache = st.session_state["career_cache"]
        careers = {n: common_ui._with_manual(n, cache.get(n, [])) for n in cands}
        pairs = all_pairs(cands, careers, rank_date, lookback)

        extra = {n for k in pairs for n in k if n not in cache}
        if extra:      # partners from outside the scanned lists
            common_ui.load_careers_bulk(client, list(extra), lookup)
        for n in extra:
            careers[n] = common_ui._with_manual(n, cache.get(n, []))

        fed_of = common_ui.load_player_federations(
            client, sorted({n for k in pairs for n in k} | set(cands)))
        for n, c in cands.items():           # a player's own federation beats the team's
            if fed_of.get(n):
                c.nf = fed_of[n]
        result = rank_teams(cands, careers, pairs, rank_date, template, avc_countries, int(min_pts),
                            fed_of=fed_of, avc_feds=avc_feds,
                             mode="pair" if method.startswith("By pair") else "player")
        st.session_state["rk_result"] = {"rows": result, "date": rank_date, "events": len(events),
                                         "players": len(cands), "min_pts": int(min_pts),
                                         "mode": "pair" if method.startswith("By pair") else "player"}
        bar.empty(); bar2.empty()
        if st.session_state.get("rk_autopub") and _can_publish():
            try:
                st.session_state["rk_autopub_msg"] = _publish_to_github(st.session_state["rk_result"])
            except Exception as pe:
                st.session_state["rk_autopub_msg"] = f"failed: {pe}"
    except Exception as e:
        st.error(str(e))

res = st.session_state.get("rk_result")
if res and any("s1" not in r for g in res["rows"].values() for r in g):
    # result made by an older version of this page: rebuild (fast - histories are still cached)
    st.info("These results were made by an older version - press **Build rankings** again "
            "(quick, the downloaded histories are reused).")
    res = None
if res:
    with st.container(border=True):
        st.subheader("2. Rankings")
        st.caption(f"As of {res['date']:%d %b %Y} · {res['events']} events scanned · "
                   f"{res['players']} AVC players found · "
                   f"{'points of the pair together' if res.get('mode') == 'pair' else 'sum of players records'}")
        all_nfs = sorted({r["nf"] for g in res["rows"].values() for r in g})
        pick = st.multiselect("Show only these federations (empty = all)", all_nfs, key="rk_nf")
        tabs = st.tabs([f"Men ({len(res['rows']['Men'])})", f"Women ({len(res['rows']['Women'])})"])
        for tab, g in zip(tabs, ("Men", "Women")):
            with tab:
                rows = [r for r in res["rows"][g] if not pick or r["nf"] in pick]
                st.dataframe([{
                    "Rank": r["rank"], "NF": r["nf"], "Player 1": r["p1"],
                    "P1 FIVB": r["p1_fivb"], "P1 AVC": r["p1_avc"], "Player 2": r["p2"],
                    "P2 FIVB": r["p2_fivb"], "P2 AVC": r["p2_avc"], "Team total": r["total"],
                    "Events together": r["events"], "Last together": r["last"].strftime("%d-%b-%Y"),
                } for r in rows], use_container_width=True, hide_index=True)

        with st.expander("🔎 Breakdown of a team (which results are counted)"):
            g_pick = st.radio("Category", ["Men", "Women"], horizontal=True, key="rk_bd_g")
            teams_g = res["rows"][g_pick]
            if not teams_g:
                st.caption("No teams.")
            else:
                idx = st.selectbox(
                    "Team", range(len(teams_g)), key=f"rk_bd_t_{g_pick}",
                    format_func=lambda i: f"{teams_g[i]['rank']}. {teams_g[i]['nf']} - "
                                          f"{teams_g[i]['p1']} / {teams_g[i]['p2']}  ({teams_g[i]['total']} pts)")
                t = teams_g[idx]
                for who, sc, nm in (("Player 1", t["s1"], t["p1"]), ("Player 2", t["s2"], t["p2"])):
                    st.markdown(f"**{nm}** — FIVB {sc.fivb_total} + AVC {sc.avc_total} = {sc.total}")
                    for side, lst in (("FIVB", sc.fivb_selected), ("AVC", sc.avc_selected)):
                        st.caption(f"{side} side - counted results")
                        st.dataframe([{
                            "Date": r.end_date.strftime("%d-%b-%Y"), "Tournament": r.tournament_name,
                            "Type": r.bucket, "Teammate": r.teammate, "Rank": r.rank, "Points": r.points,
                        } for r in lst] or [{"Date": "-", "Tournament": "(none)", "Type": "", "Teammate": "",
                                             "Rank": None, "Points": 0}],
                            use_container_width=True, hide_index=True)

        if st.button("Generate Excel", type="primary", key="rk_xl"):
            logo_path = None
            if logo_file is not None:
                logo_path = str(pathlib.Path(tempfile.gettempdir()) / f"avc_logo_{logo_file.name}")
                with open(logo_path, "wb") as f:
                    f.write(logo_file.getbuffer())
            out = str(pathlib.Path(tempfile.gettempdir()) / "Asian_Rankings.xlsx")
            build_ranking_workbook("AVC Beach Tour - Asian Team Rankings", res["date"], res["rows"], out, logo_path,
                                   template["fivb_side"]["max_events"])
            with open(out, "rb") as f:
                st.session_state["rk_file"] = f.read()
        if st.session_state.get("rk_file"):
            st.download_button("⬇️ Download Asian Rankings", st.session_state["rk_file"],
                               file_name=f"Asian_Rankings_{res['date']:%Y%m%d}.xlsx", key="rk_dl")

    with st.container(border=True):
        st.subheader("3. Public web page")
        st.caption("One self-contained page (`index.html`) that anyone can open - no login: Men / Women tabs, "
                   "search, federation filter and a click-to-open breakdown. The page can hold SEVERAL "
                   "rankings (shown as buttons at the top, each with its own link `index.html#id`): upload "
                   "your current `index.html` and this ranking is added to it - or replaces the ranking "
                   "with the same ID - so the other rankings stay. It contains only ranking data (no VIS "
                   "login details). Upload it to any web hosting, e.g. GitHub Pages.")
        c1, c2 = st.columns(2)
        site_title = c1.text_input("Site title", value="AVC Beach Volleyball Rankings", key="rk_pub_title")
        rk_name = c2.text_input("This ranking's name (button)", value="Asian Rankings", key="rk_pub_name")
        c3, c4 = st.columns(2)
        rk_id = c3.text_input("ID (used in the link)", value="asian-rankings", key="rk_pub_id",
                              help="Letters, digits and dashes. Using an existing ID replaces that ranking.")
        rk_desc = c4.text_input("Short description (optional)", value="", key="rk_pub_desc")
        prev = st.file_uploader("Optional: your current index.html (to keep its other rankings)",
                                type=["html"], key="rk_pub_prev")
        if st.button("Generate public web page", key="rk_pub"):
            site = None
            if prev is not None:
                site = extract_site(prev.getvalue().decode("utf-8", errors="replace"))
                if site is None:
                    st.error("That file was not made by this tool - upload the index.html you downloaded here.")
            if prev is None or site is not None:
                site = _site_with(res, site, site_title, rk_name, rk_id, rk_desc, logo_file)
                st.session_state["rk_pub_html"] = build_site_html(site)
                st.session_state["rk_pub_how"] = build_explainer_html(site)
                st.session_state["rk_pub_list"] = [f"{r['name']} (#{r['id']}, {r['date']})" for r in site["rankings"]]
        st.markdown("**Publish the public page directly**" + (" (asianvolleyball.com)" if _pg_config() else " (GitHub Pages)" if _gh_config() else ""))
        if _can_publish():
            st.checkbox("Publish automatically after every *Build rankings*", key="rk_autopub",
                        help="Each Build then updates the live page (keeping the other rankings on it).")
            if st.button("Publish now", key="rk_gh_now"):
                try:
                    st.session_state["rk_autopub_msg"] = _publish_to_github(res)
                except Exception as pe:
                    st.session_state["rk_autopub_msg"] = f"failed: {pe}"
            m = st.session_state.get("rk_autopub_msg")
            if m == "published":
                st.success("Live page updated." + (" Open it: " + _pg_config()[0].rsplit("/", 1)[0] + "/" if _pg_config() else " (GitHub shows it within a minute or two)"))
            elif m == "unchanged":
                st.info("Nothing changed - the live page already shows this ranking.")
            elif m:
                st.error(f"Publish {m}")
        else:
            st.caption("Not set up. Add the [playground] key (or a GitHub token) to the app's secrets to enable "
                       "one-click / automatic publishing (see the steps below).")
        with st.expander("Set up automatic publishing"):
            st.markdown(
                "**AVC server (asianvolleyball.com/playground/rankings/)** — used when set up:\n"
                "1. `publish.php` and `publish-key.php` in the `playground/rankings/` folder on the server "
                "(the folder must be writable by the web server).\n"
                "2. Check: opening `https://asianvolleyball.com/playground/rankings/publish.php` in a browser shows "
                "`{\"ok\":false,\"error\":\"Invalid or missing key\"}`.\n"
                "3. On Streamlit Cloud: app **⋮ → Settings → Secrets**, add:\n"
                "```toml\n[playground]\nurl = \"https://asianvolleyball.com/playground/rankings/publish.php\"\n"
                "key = \"the key inside publish-key.php\"\n```\n\n"
                "**Or GitHub Pages:** a token with *Contents: Read and write* on the rankings repo, and "
                "`[github]` token / repo / branch in the secrets.\n\n"
                "Careful: with the checkbox on, every Build replaces what the public sees.")
        if st.session_state.get("rk_pub_html"):
            st.success("Rankings in this page: " + "; ".join(st.session_state["rk_pub_list"]))
            import io, zipfile
            _buf = io.BytesIO()
            with zipfile.ZipFile(_buf, "w", zipfile.ZIP_DEFLATED) as _z:
                _z.writestr("index.html", st.session_state["rk_pub_html"])
                _z.writestr("how-it-works.html", st.session_state["rk_pub_how"])
            st.download_button("⬇️ Download the web page (zip: index.html + how-it-works.html)", _buf.getvalue(),
                               file_name="rankings_web.zip", mime="application/zip", key="rk_pub_dl")
            st.download_button("⬇️ Download index.html only", st.session_state["rk_pub_html"].encode("utf-8"),
                               file_name="index.html", mime="text/html", key="rk_pub_dl1")
            with st.expander("How to publish it on GitHub Pages"):
                st.markdown(
                    "1. On GitHub create a new **public** repository (e.g. `rankings`).\n"
                    "2. **Add file → Upload files**, drop **both** `index.html` and `how-it-works.html` (unzip the download first), **Commit**.\n"
                    "3. **Settings → Pages → Branch: main / (root) → Save**.\n"
                    "4. After a minute the page is live at `https://<your-account>.github.io/rankings/`; "
                    "one ranking directly: `.../rankings/#asian-rankings`.\n\n"
                    "To update or add a ranking: build it here, upload your current `index.html` above, "
                    "download the new zip and upload both files over the old ones on GitHub.")
