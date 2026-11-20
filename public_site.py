"""
public_site.py
--------------
Builds ONE self-contained web page (index.html, data embedded, no logins, no external
files) that anyone can open to browse the Asian Rankings: Men / Women tabs, search,
federation filter, and a click-to-open breakdown of the counted results.

The page holds only ranking data (names, points, results) - never VIS credentials.
Publish it anywhere that serves static files (e.g. GitHub Pages).
"""
import html
import json
import re
from datetime import date
from typing import Dict, List, Optional

from country_codes import excel_code
from excel_export import _bucket_label


def _results(lst) -> List[dict]:
    return [{"d": r.end_date.strftime("%d-%b-%Y"), "t": r.tournament_name,
             "k": _bucket_label(r.bucket, r.tournament_name), "m": r.teammate,
             "r": r.rank, "p": r.points} for r in lst]


def _player(name, nf, sc) -> dict:
    return {"n": name, "nf": excel_code(nf), "fivb": sc.fivb_total, "avc": sc.avc_total,
            "fr": _results(sc.fivb_selected), "ar": _results(sc.avc_selected)}


def explain_dict(template: Optional[dict], mode: str, min_points: int = 0) -> dict:
    """The numbers behind the 'How the ranking works' page (taken from the scoring template used)."""
    t = template or {}
    return {
        "days": t.get("lookback_days", 365),
        "nf": t.get("fivb_side", {}).get("max_events", 4),
        "na": t.get("avc_side", {}).get("max_events", 4),
        "champ": t.get("avc_side", {}).get("caps", {}).get("championship"),
        "glob": (t.get("global_cap_groups") or [{}])[0].get("limit"),
        "mode": mode, "min": min_points,
    }


def ranking_to_dict(rid: str, name: str, rows_by_gender: Dict[str, List[dict]], ranking_date: date,
                    description: str = "", mode: str = "player",
                    template: Optional[dict] = None, min_points: int = 0) -> dict:
    """One ranking of the site. kind='team' = pairs ranked by combined points."""
    teams = {}
    for g in ("Men", "Women"):
        teams[g] = [{
            "rank": r["rank"], "nf": excel_code(r["nf"]), "total": r["total"],
            "events": r.get("events"), "last": r["last"].strftime("%d-%b-%Y") if r.get("last") else "",
            "p": [_player(r["p1"], r["p1_nf"], r["s1"]), _player(r["p2"], r["p2_nf"], r["s2"])],
        } for r in rows_by_gender.get(g, [])]
    players = {}
    for g in ("Men", "Women"):
        seen = {}
        for r in rows_by_gender.get(g, []):
            for no, nm, nf, key, inn in ((r.get("p1_no"), r["p1"], r["p1_nf"], "w1", r.get("p1_in", True)),
                                         (r.get("p2_no"), r["p2"], r["p2_nf"], "w2", r.get("p2_in", True))):
                w = r.get(key)
                if w is None or not inn:
                    continue
                k = no or (nm, nf)
                if k not in seen:
                    seen[k] = _player(nm, nf, w)
        lst = sorted(seen.values(), key=lambda x: (-(x["fivb"] + x["avc"]), x["n"]))
        players[g] = [x for x in lst if x["fivb"] + x["avc"] > 0]
    return {"id": rid, "name": name, "description": description, "kind": "team", "players": players,
            "date": ranking_date.strftime("%d %B %Y"), "iso": ranking_date.isoformat(),
            "categories": ["Men", "Women"], "mode": mode, "explain": explain_dict(template, mode, min_points), "teams": teams}


def new_site(title: str = "AVC Beach Volleyball Rankings", logo_data_url: Optional[str] = None,
             footer: str = "Points follow the AVC Entry / Seeding points rules.") -> dict:
    return {"title": title, "logo": logo_data_url or "", "footer": footer, "rankings": []}


def add_ranking(site: dict, ranking: dict) -> dict:
    """Replace the ranking with the same id, otherwise append (other rankings are kept)."""
    lst = site.get("rankings", [])
    for i, r in enumerate(lst):
        if r["id"] == ranking["id"]:
            lst[i] = ranking
            break
    else:
        lst.append(ranking)
    site["rankings"] = lst
    return site


def extract_site(html: str) -> Optional[dict]:
    """Read the data back out of an index.html made by this module (to add to it later)."""
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(1).replace("<\\/", "</"))
    except ValueError:
        return None
    if "rankings" in d:
        return d
    if "teams" in d:      # first version: a single Asian ranking
        r = {"id": "asian-rankings", "name": "Asian Rankings", "description": "", "kind": "team",
             "date": d.get("date", ""), "iso": "", "categories": ["Men", "Women"], "teams": d["teams"]}
        return {"title": d.get("title", "AVC Beach Volleyball Rankings"), "logo": d.get("logo", ""),
                "footer": d.get("footer", ""), "rankings": [r]}
    return None


def _meta(site: dict) -> dict:
    """Flags (inline SVG data URLs) and zones for the federations that appear in the rankings."""
    from urllib.parse import quote
    from flag_data import NF_TO_ISO2, ZONES, ZONE_COLORS, FLAG_SVG
    nfs = set()
    for r in site.get("rankings", []):
        for lst in r.get("teams", {}).values():
            for t in lst:
                nfs.add(t["nf"])
                nfs.update(p["nf"] for p in t["p"])
    zone_of = {nf: z for z, members in ZONES.items() for nf in members}
    flag, zone = {}, {}
    for nf in nfs:
        iso = NF_TO_ISO2.get(nf)
        if iso in FLAG_SVG:
            flag[nf] = "data:image/svg+xml;utf8," + quote(FLAG_SVG[iso])
        zone[nf] = zone_of.get(nf, "Other")
    used = [z for z in list(ZONES) + ["Other"] if z in set(zone.values())]
    return {"flag": flag, "zone": zone,
            "zones": [{"name": z, "color": ZONE_COLORS.get(z, "#6b7280")} for z in used]}


def build_site_html(site: dict) -> str:
    site = dict(site, meta=_meta(site))
    blob = json.dumps(site, ensure_ascii=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", blob).replace("__TITLE__", site["title"].replace("<", "&lt;"))


def build_public_html(rows_by_gender, ranking_date, title="Asian Beach Volleyball Team Rankings",
                      logo_data_url=None, footer="Points follow the AVC Entry / Seeding points rules."):
    """Single-ranking convenience wrapper (kept for compatibility)."""
    site = new_site(title, logo_data_url, footer)
    add_ranking(site, ranking_to_dict("asian-rankings", "Asian Rankings", rows_by_gender, ranking_date))
    return build_site_html(site)


def build_explainer_html(site: dict) -> str:
    """The separate 'How the ranking works' page (how-it-works.html), made from the same data."""
    data = {"title": site.get("title", ""), "logo": site.get("logo", ""),
            "rankings": [{"id": r["id"], "name": r["name"], "date": r["date"], "explain": r.get("explain")}
                         for r in site.get("rankings", [])]}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return _EXPLAIN.replace("__TITLE__", html.escape(site.get("title", "Rankings")) + " - How the ranking works") \
                   .replace("__DATA__", blob)


_EXPLAIN = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f3f5f9;--card:#fff;--ink:#121722;--mute:#5b6676;--line:#e2e6ee;--accent:#0b2f6b;--accent2:#1d57b8;--soft:#eef2f9}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0d1118;--card:#161b24;--ink:#e8ecf2;--mute:#97a2b2;--line:#273041;--accent:#16356e;--accent2:#3b6fd0;--soft:#1c2432}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans Thai",sans-serif}
.hero{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;padding:26px 16px 64px}
.wrap{max-width:860px;margin:0 auto;padding:0 16px}
.hero .wrap{padding:0}
header{display:flex;align-items:center;gap:16px}
header img{height:60px;width:auto;background:#fff;border-radius:12px;padding:6px}
h1{font-size:clamp(23px,4vw,34px);margin:0;line-height:1.15;letter-spacing:-.01em}
.sub{opacity:.88;margin-top:6px;font-size:14px}
.back{display:inline-block;margin-bottom:14px;color:#fff;text-decoration:none;font-weight:600;font-size:14px;opacity:.9}
.back:hover{text-decoration:underline}
.pills{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.pills[hidden]{display:none}
.pills a{background:rgba(255,255,255,.16);color:#fff;text-decoration:none;border-radius:999px;padding:6px 14px;font-weight:600;font-size:14px;border:1px solid rgba(255,255,255,.35)}
.pills a[aria-current=true]{background:#fff;color:var(--accent)}
main{margin-top:-40px;padding-bottom:48px}
section{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px 24px;margin-bottom:16px;box-shadow:0 6px 24px rgba(10,25,60,.06)}
h2{margin:0 0 10px;font-size:20px;display:flex;align-items:center;gap:12px}
h2 b{display:inline-flex;width:30px;height:30px;border-radius:50%;background:var(--accent2);color:#fff;font-size:15px;align-items:center;justify-content:center;flex:none}
p{margin:8px 0}
ul{margin:8px 0;padding-left:22px}li{margin:4px 0}
.muted{color:var(--mute);font-size:14px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:10px}
.box{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:var(--soft)}
.box h3{margin:0 0 6px;font-size:15px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:12px 0}
.tile{text-align:center;border:1px solid var(--line);border-radius:12px;padding:14px 8px;background:var(--soft)}
.tile big{display:block;font-size:30px;font-weight:800;color:var(--accent2);line-height:1.1}
.tile span{font-size:13px;color:var(--mute)}
table{width:100%;border-collapse:collapse;margin:10px 0;font-size:14.5px}
th,td{padding:8px 10px;border-top:1px solid var(--line);text-align:left}
th{background:var(--soft);font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.btn{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;font-weight:700;border-radius:999px;padding:10px 20px}
@media (max-width:640px){.cols{grid-template-columns:1fr}section{padding:18px 16px}}
</style>
</head>
<body>
<div class="hero"><div class="wrap">
  <a class="back" id="back" href="index.html">&larr; Back to the rankings</a>
  <header><img id="logo" alt="" hidden><div><h1>How the ranking works</h1><div class="sub" id="sub"></div></div></header>
  <nav class="pills" id="pills" hidden></nav>
</div></div>
<main class="wrap" id="main"></main>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
  var D=JSON.parse(document.getElementById('data').textContent), $=function(i){return document.getElementById(i)};
  if(D.logo){ $('logo').src=D.logo; $('logo').hidden=false; }
  function esc(t){ var d=document.createElement('div'); d.textContent=t; return d.innerHTML; }
  function sec(n,title,body){ return '<section><h2><b>'+n+'</b>'+title+'</h2>'+body+'</section>'; }
  function page(R){
    var E=R.explain||{days:365,nf:4,na:4,mode:'player',min:0}, pair=E.mode==='pair', h='';
    h+=sec(1,'Overview','<p>This ranking lists the beach volleyball teams of the Asian Volleyball Confederation (AVC) federations, as of <b>'+esc(R.date)+'</b>. '
      +'Points are scored with the same rules as the AVC Entry / Seeding points. Only players of AVC federations are included.</p>');
    h+=sec(2,'Which results count','<p>Only events that <b>finished within the last '+E.days+' days</b> before the ranking date count. They fall on two sides:</p>'
      +'<div class="cols"><div class="box"><h3>FIVB side</h3><ul><li>FIVB Beach Pro Tour</li><li>World Championships</li><li>Olympic Games</li><li>National Tours</li><li>Multi-sport games hosted outside AVC</li></ul></div>'
      +'<div class="box"><h3>AVC side</h3><ul><li>AVC Continental Tour</li><li>Zonal events</li><li>AVC Championships</li><li>Under-age events</li><li>Multi-sport games hosted in an AVC country</li></ul></div></div>'
      +'<p class="muted">Events of other confederations, test events and snow volleyball are not counted.</p>');
    var caps='';
    if(E.champ!=null) caps+='<li>At most <b>'+E.champ+'</b> AVC Championship result counts.</li>';
    if(E.glob!=null) caps+='<li>At most <b>'+E.glob+'</b> Multi-sport or Zonal result counts in total (FIVB and AVC sides together).</li>';
    h+=sec(3,'How many results count','<p>Each side keeps only the player\'s best results:</p>'
      +'<div class="tiles"><div class="tile"><big>'+E.nf+'</big><span>best FIVB-side results</span></div><div class="tile"><big>'+E.na+'</big><span>best AVC-side results</span></div></div>'
      +(caps?'<p>Limits:</p><ul>'+caps+'</ul>':''));
    h+=sec(4,'Player points','<p>A player\'s points = points of the counted <b>FIVB-side</b> results + points of the counted <b>AVC-side</b> results, as earned in the FIVB VIS system. '
      +'The <b>Players</b> tabs show exactly this: one row per player, with his or her own points over the whole record, whoever the partner was.</p>');
    var ex = pair
      ? '<p>The team ranking counts <b>only the results the two players earned together</b>. The same best-results rules and limits are applied to those results, and the team total is the points of both players added up. '
        +'A player who played with two partners appears in two teams, each with its own points.</p>'
        +'<p class="muted">Example (illustrative numbers): A and B earned 300 each at one event and 200 each at another. A also played an event with C and earned 400 each.</p>'
        +'<table><tr><th>Team</th><th class="n">Calculation</th><th class="n">Total</th></tr>'
        +'<tr><td>A / B</td><td class="n">(300 + 200) + (300 + 200)</td><td class="n"><b>1000</b></td></tr>'
        +'<tr><td>A / C</td><td class="n">400 + 400</td><td class="n"><b>800</b></td></tr></table>'
        +'<p class="muted">On the Players tab, A has 300 + 200 + 400 = 900 points, B has 500 and C has 400.</p>'
      : '<p>Team total = <b>player 1 points + player 2 points</b>, where each player\'s points are his or her whole record, including results with other partners.</p>'
        +'<p class="muted">Example (illustrative numbers): A has 900 points, B has 500 and C has 400. Team A / B = 900 + 500 = <b>1400</b>; team A / C = 900 + 400 = <b>1300</b>.</p>';
    h+=sec(5,'Team points',ex);
    h+=sec(6,'Ties and updates','<ul><li>Teams with the same total share the same rank.</li>'
      +(E.min>1?'<li>Teams with fewer than '+E.min+' points are not listed.</li>':'')
      +'<li>The ranking is a snapshot as of the date shown; it is rebuilt from FIVB VIS data whenever a new version is published.</li>'
      +'<li>Click a team (or a player) in the ranking to see the exact results behind the points.</li></ul>'
      +'<p style="margin-top:16px"><a class="btn" href="index.html#'+esc(R.id)+'">&larr; Back to the ranking</a></p>');
    return h;
  }
  function pick(id){
    var R=D.rankings.filter(function(r){return r.id===id;})[0]||D.rankings[D.rankings.length-1];
    if(!R){ $('main').innerHTML='<section>No rankings published yet.</section>'; return; }
    $('sub').textContent=D.title+' - '+R.name;
    $('back').href='index.html#'+R.id;
    $('main').innerHTML=page(R);
    var pills=$('pills'); pills.innerHTML=''; pills.hidden=D.rankings.length<2;
    D.rankings.forEach(function(r){ var a=document.createElement('a'); a.textContent=r.name; a.href='#'+r.id; a.setAttribute('aria-current', r.id===R.id); pills.appendChild(a); });
  }
  window.addEventListener('hashchange',function(){ pick(location.hash.slice(1)); window.scrollTo(0,0); });
  pick(location.hash.slice(1));
})();
</script>
</body>
</html>
"""


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f3f5f9;--card:#fff;--ink:#121722;--mute:#5b6676;--line:#e2e6ee;--accent:#0b2f6b;--accent2:#1d57b8;--accent-ink:#fff;--soft:#eef2f9;--gold:#d9a521;--silver:#9aa5b4;--bronze:#c27a43;--bar:#cfd9ee}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0d1118;--card:#161b24;--ink:#e8ecf2;--mute:#97a2b2;--line:#273041;--accent:#16356e;--accent2:#3b6fd0;--accent-ink:#fff;--soft:#1c2432;--bar:#2a3a5c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans Thai",sans-serif}
.hero{background:linear-gradient(135deg,var(--accent),var(--accent2));color:var(--accent-ink);padding:26px 16px 70px}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px}
.hero .wrap{padding:0}
header{display:flex;align-items:center;gap:16px}
header img{height:68px;width:auto;background:#fff;border-radius:12px;padding:6px}
h1{font-size:clamp(21px,3.6vw,31px);margin:0;line-height:1.15;letter-spacing:-.01em}
.sub{opacity:.85;margin-top:5px;font-size:14px}
main{margin-top:-52px;padding-bottom:48px}
.pills{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 12px}
.pills[hidden]{display:none}
.pills a{background:var(--card);color:var(--accent2);text-decoration:none;border-radius:999px;padding:7px 16px;font-weight:600;font-size:14px;border:1px solid var(--line);box-shadow:0 2px 8px rgba(10,25,60,.08)}
.pills a[aria-current=true]{background:var(--accent);color:#fff;border-color:var(--accent)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:0 6px 24px rgba(10,25,60,.08);overflow:hidden}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:14px}
.tabs{display:inline-flex;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.tabs button{border:0;background:none;color:var(--ink);padding:9px 20px;font:inherit;font-weight:700;cursor:pointer}
.tabs button[aria-selected=true]{background:var(--accent);color:#fff}
tr.team .sm{font-size:12px;color:var(--mute);font-weight:400}
input,select{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 12px;min-height:40px}
input{flex:1 1 200px;min-width:0}
.count{color:var(--mute);font-size:13px;margin-left:auto}
.zones{display:flex;flex-wrap:wrap;gap:8px;padding:0 14px 14px}
.zone{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:5px 12px;font:inherit;font-size:13px;font-weight:600;cursor:pointer}
.zone i{width:10px;height:10px;border-radius:50%;background:var(--c)}
.zone[aria-pressed=true]{background:var(--c);border-color:var(--c);color:#fff}
.zone[aria-pressed=true] i{background:#fff}
table{width:100%;border-collapse:collapse}
th,td{padding:11px 12px;text-align:left;border-top:1px solid var(--line);vertical-align:middle}
th{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);background:var(--soft)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.rk{width:58px}
.medal{display:inline-flex;width:30px;height:30px;border-radius:50%;align-items:center;justify-content:center;font-weight:800;color:#fff;font-size:14px}
.m1{background:var(--gold)}.m2{background:var(--silver)}.m3{background:var(--bronze)}
.rkn{font-weight:700;color:var(--mute);padding-left:9px}
tr.team{cursor:pointer}
tr.team td:first-child{box-shadow:inset 5px 0 0 var(--z,transparent)}
tr.team:hover td{background:var(--soft)}
tr.team:focus-visible{outline:2px solid var(--accent2);outline-offset:-2px}
.nfc{display:inline-flex;align-items:center;gap:8px;font-weight:700;font-size:13px}
.flag{width:28px;height:19px;border-radius:3px;box-shadow:0 0 0 1px rgba(0,0,0,.18);object-fit:cover;flex:none}
.names div{white-space:normal}
.names div{font-weight:600}
.tot{font-weight:800;font-size:17px}
tr.detail td{background:var(--soft);padding:16px}
.pl{margin-bottom:16px}.pl:last-child{margin-bottom:0}
.pl h3{margin:0 0 6px;font-size:15px;display:flex;align-items:center;gap:8px}
.pl h4{margin:10px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute)}
.res{width:100%;font-size:13px;background:var(--card);border:1px solid var(--line);border-radius:8px}
.res td,.res th{padding:6px 8px;background:none}
.res th{background:var(--soft)}
.res td:first-child{white-space:nowrap}
.none{color:var(--mute);font-size:13px}
.empty{padding:28px;text-align:center;color:var(--mute)}
.howbtn{display:inline-block;margin-top:14px;background:#fff;color:var(--accent);font-weight:700;text-decoration:none;border-radius:999px;padding:9px 18px;font-size:14px;box-shadow:0 2px 10px rgba(0,0,0,.18)}
.howbtn:hover{filter:brightness(.95)}
.howbtn[hidden]{display:none}
footer{margin-top:18px;color:var(--mute);font-size:13px;text-align:center}
@media (max-width:720px){
  .hide-s{display:none}
  th,td{padding:10px 8px}
  .hero{padding-bottom:64px}
  header img{height:48px}
  .tabs{width:100%;overflow-x:auto}.tabs button{flex:1;white-space:nowrap;padding:9px 6px;font-size:12.5px}
}
</style>
</head>
<body>
<div class="hero"><div class="wrap">
  <header>
    <img id="logo" alt="" hidden>
    <div><h1 id="title"></h1><div class="sub" id="asof"></div></div>
  </header>
  <a class="howbtn" id="how" href="how-it-works.html" hidden>How the ranking works &rarr;</a>
</div></div>
<main class="wrap">
  <nav class="pills" id="pills" aria-label="Rankings" hidden></nav>
  <div class="panel">
    <div class="bar">
      <div class="tabs" id="tabs" role="tablist" aria-label="Category"></div>
      <input id="q" type="search" placeholder="Search a player or country" aria-label="Search">
      <select id="nf" aria-label="Federation"><option value="">All federations</option></select>
      <span class="count" id="count"></span>
    </div>
    <div class="zones" id="zones" aria-label="Filter by zone"></div>
    <table>
      <thead><tr id="thead"></tr></thead>
      <tbody id="body"></tbody>
    </table>
    <div class="empty" id="empty" hidden>No teams match.</div>
  </div>
  <footer id="foot"></footer>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
  var D = JSON.parse(document.getElementById('data').textContent), M = D.meta || {flag:{},zone:{},zones:[]};
  var R = null, cat = '', open = null, zoneSel = null;
  var $ = function(id){return document.getElementById(id)};
  var ZC = {}; M.zones.forEach(function(z){ ZC[z.name]=z.color; });
  $('title').textContent = D.title; $('foot').textContent = D.footer;
  if (D.logo){ $('logo').src = D.logo; $('logo').hidden = false; }
  function el(tag, cls, text){ var e=document.createElement(tag); if(cls) e.className=cls; if(text!==undefined) e.textContent=text; return e; }
  function zoneColor(nf){ return ZC[M.zone[nf]] || ''; }
  function flag(nf){ if(!M.flag[nf]) return null; var i=el('img','flag'); i.src=M.flag[nf]; i.alt=''; i.loading='lazy'; return i; }
  function nfBadge(nf){ var s=el('span','nfc'), f=flag(nf); if(f) s.appendChild(f); s.appendChild(document.createTextNode(nf)); return s; }
  var PLAYERS = null;
  function isPl(c){ return c.indexOf(' players')>0; }
  function buildPlayers(c){
    var g=c.split(' ')[0], list;
    if(R.players && R.players[g]) list=R.players[g].map(function(p){ return {n:p.n,nf:p.nf,fivb:p.fivb,avc:p.avc,fr:p.fr,ar:p.ar,best:p.fivb+p.avc}; });
    else { var map={};   // older files: best entry found in the pairs
      (R.teams[g]||[]).forEach(function(t){ t.p.forEach(function(p){ var k=p.n+'|'+p.nf, pts=p.fivb+p.avc;
        if(!map[k]||pts>map[k].best) map[k]={n:p.n,nf:p.nf,fivb:p.fivb,avc:p.avc,fr:p.fr,ar:p.ar,best:pts}; }); });
      list=Object.keys(map).map(function(k){return map[k];}); }
    list.sort(function(a,b){return b.best-a.best||a.n.localeCompare(b.n);});
    var prev=null,rank=0; list.forEach(function(e,i){ if(e.best!==prev){rank=i+1;prev=e.best;} e.rank=rank; });
    return list;
  }
  function plist(){ if(!PLAYERS) PLAYERS={}; return PLAYERS[cat] || (PLAYERS[cat]=buildPlayers(cat)); }
  function setHead(cols){
    var h=$('thead'); h.innerHTML='';
    cols.forEach(function(c){ var th=el('th',c[1]||'',c[0]); h.appendChild(th); });
  }
  function playerDetail(e){
    var tr=el('tr','detail'), td=el('td'); td.colSpan=6; var box=el('div','pl');
    box.appendChild(el('h4','','FIVB side - '+e.fivb+' pts')); box.appendChild(resultsTable(e.fr));
    box.appendChild(el('h4','','AVC side - '+e.avc+' pts')); box.appendChild(resultsTable(e.ar));
    td.appendChild(box); tr.appendChild(td); return tr;
  }
  function renderPlayers(){
    var q=$('q').value.trim().toLowerCase(), nf=$('nf').value, body=$('body'), P=plist();
    body.innerHTML='';
    setHead([['#'],['NF'],['Player'],['FIVB','num hide-s'],['AVC','num hide-s'],['Points','num']]);
    var list=P.filter(function(e){
      if(zoneSel && M.zone[e.nf]!==zoneSel) return false;
      if(nf && e.nf!==nf) return false;
      return !q || (e.n+' '+e.nf).toLowerCase().indexOf(q)>=0;
    });
    list.forEach(function(e){
      var key='P'+cat+e.n+e.nf, z=zoneColor(e.nf);
      var tr=el('tr','team'); tr.tabIndex=0; if(z) tr.style.setProperty('--z',z);
      var rk=el('td','rk'); rk.appendChild(e.rank<=3?el('span','medal m'+e.rank,String(e.rank)):el('span','rkn',String(e.rank))); tr.appendChild(rk);
      var c=el('td'); c.appendChild(nfBadge(e.nf)); tr.appendChild(c);
      tr.appendChild(el('td','names')).appendChild(el('div','',e.n));
      tr.appendChild(el('td','num hide-s',String(e.fivb))); tr.appendChild(el('td','num hide-s',String(e.avc)));
      var tot=el('td','num'); tot.appendChild(el('div','tot',String(e.best))); tr.appendChild(tot);
      var toggle=function(){ open=(open===key)?null:key; render(); };
      tr.addEventListener('click',toggle);
      tr.addEventListener('keydown',function(ev){ if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();toggle();} });
      body.appendChild(tr); if(open===key) body.appendChild(playerDetail(e));
    });
    $('empty').hidden=list.length>0;
    $('count').textContent=list.length+' of '+P.length+' players';
  }
  function fillFilters(){
    var s=$('nf'), keep=s.value, set={}, zs={};
    if(isPl(cat)){ plist().forEach(function(e){ set[e.nf]=1; zs[M.zone[e.nf]]=(zs[M.zone[e.nf]]||0)+1; }); }
    else R.teams[cat].forEach(function(t){ set[t.nf]=1; zs[M.zone[t.nf]]=(zs[M.zone[t.nf]]||0)+1; t.p.forEach(function(p){ set[p.nf]=1; }); });
    s.innerHTML=''; s.appendChild(new Option('All federations',''));
    Object.keys(set).sort().forEach(function(n){ s.appendChild(new Option(n,n)); });
    s.value = set[keep] ? keep : '';
    var zb=$('zones'); zb.innerHTML='';
    M.zones.forEach(function(z){
      if(!zs[z.name]) return;
      var b=el('button','zone'); b.style.setProperty('--c',z.color); b.setAttribute('aria-pressed', zoneSel===z.name);
      b.appendChild(el('i')); b.appendChild(document.createTextNode(z.name + ' (' + zs[z.name] + ')'));
      b.onclick=function(){ zoneSel = (zoneSel===z.name)?null:z.name; open=null; fillFilters(); render(); };
      zb.appendChild(b);
    });
    zb.hidden = !zb.children.length;
  }
  function resultsTable(list, noMate){
    if(!list.length) return el('div','none','No counted results.');
    var t=el('table','res'), h=el('tr');
    ['Date','Tournament','Type','Teammate','Rank','Pts'].forEach(function(x,i){ if(noMate&&i==3) return; var c=el('th','',x); if(i==2||i==3) c.className='hide-s'; if(i>=4) c.className='num'; h.appendChild(c); });
    t.appendChild(h);
    list.forEach(function(r){
      var tr=el('tr');
      tr.appendChild(el('td','',r.d)); tr.appendChild(el('td','',r.t));
      tr.appendChild(el('td','hide-s',r.k)); if(!noMate) tr.appendChild(el('td','hide-s',r.m||''));
      tr.appendChild(el('td','num',r.r==null?'':String(r.r))); tr.appendChild(el('td','num',String(r.p)));
      t.appendChild(tr);
    });
    return t;
  }
  function merge(a,b){
    var m={}, out=[];
    (a||[]).concat(b||[]).forEach(function(r){ var k=r.d+'|'+r.t+'|'+r.k; if(m[k]){ m[k].p+=r.p; } else { m[k]={d:r.d,t:r.t,k:r.k,r:r.r,p:r.p}; out.push(m[k]); } });
    out.sort(function(x,y){ return y.p-x.p; });
    return out;
  }
  function pairDetail(team){
    var tr=el('tr','detail'), td=el('td'); td.colSpan=6; var a=team.p[0], b=team.p[1];
    var box=el('div','pl'), h=el('h3');
    h.appendChild(document.createTextNode(a.n+' / '+b.n+' - '+team.total+' pts together')); box.appendChild(h);
    box.appendChild(el('h4','','FIVB side - '+(a.fivb+b.fivb)+' pts')); box.appendChild(resultsTable(merge(a.fr,b.fr),true));
    box.appendChild(el('h4','','AVC side - '+(a.avc+b.avc)+' pts')); box.appendChild(resultsTable(merge(a.ar,b.ar),true));
    td.appendChild(box);
    if(team.events){ td.appendChild(el('div','none','Played together in ' + team.events + ' event' + (team.events>1?'s':'') + (team.last?' (latest ' + team.last + ')':'') + '.')); }
    tr.appendChild(td); return tr;
  }
  function detail(team){
    if(R.mode==='pair') return pairDetail(team);
    var tr=el('tr','detail'), td=el('td'); td.colSpan=6;
    team.p.forEach(function(p){
      var box=el('div','pl'), h=el('h3'); var f=flag(p.nf); if(f) h.appendChild(f);
      h.appendChild(document.createTextNode(p.n + ' (' + p.nf + ') - ' + (p.fivb+p.avc) + ' pts')); box.appendChild(h);
      box.appendChild(el('h4','','FIVB side - ' + p.fivb + ' pts')); box.appendChild(resultsTable(p.fr));
      box.appendChild(el('h4','','AVC side - ' + p.avc + ' pts')); box.appendChild(resultsTable(p.ar));
      td.appendChild(box);
    });
    if(team.events){ td.appendChild(el('div','none','Played together in ' + team.events + ' event' + (team.events>1?'s':'') + (team.last?' (latest ' + team.last + ')':'') + '.')); }
    tr.appendChild(td); return tr;
  }
  function render(){
    if(isPl(cat)) return renderPlayers();
    setHead([['#'],['NF'],['Team'],['FIVB','num hide-s'],['AVC','num hide-s'],['Total','num']]);
    var q=$('q').value.trim().toLowerCase(), nf=$('nf').value, body=$('body');
    var all=R.teams[cat], max=all.length?all[0].total:1; body.innerHTML='';
    var list=all.filter(function(t){
      if(zoneSel && M.zone[t.nf]!==zoneSel) return false;
      if(nf && t.nf!==nf && t.p[0].nf!==nf && t.p[1].nf!==nf) return false;
      if(!q) return true;
      return (t.nf+' '+t.p[0].n+' '+t.p[1].n).toLowerCase().indexOf(q)>=0;
    });
    list.forEach(function(t,i){
      var key=cat+i+t.p[0].n+t.p[1].n, z=zoneColor(t.nf);
      var tr=el('tr','team'); tr.tabIndex=0; tr.setAttribute('aria-expanded', open===key); if(z) tr.style.setProperty('--z',z);
      var rk=el('td','rk');
      rk.appendChild(t.rank<=3 ? el('span','medal m'+t.rank,String(t.rank)) : el('span','rkn',String(t.rank)));
      tr.appendChild(rk);
      var c=el('td'); c.appendChild(nfBadge(t.nf)); tr.appendChild(c);
      var n=el('td','names'); n.appendChild(el('div','p1',t.p[0].n)); n.appendChild(el('div','',t.p[1].n)); tr.appendChild(n);
      var f=el('td','num hide-s'); if(R.mode==='pair'){ f.appendChild(el('div','',String(t.p[0].fivb+t.p[1].fivb))); } else { f.appendChild(el('div','',String(t.p[0].fivb))); f.appendChild(el('div','',String(t.p[1].fivb))); } tr.appendChild(f);
      var a=el('td','num hide-s'); if(R.mode==='pair'){ a.appendChild(el('div','',String(t.p[0].avc+t.p[1].avc))); } else { a.appendChild(el('div','',String(t.p[0].avc))); a.appendChild(el('div','',String(t.p[1].avc))); } tr.appendChild(a);
      var tot=el('td','num'); tot.appendChild(el('div','tot',String(t.total)));
      tr.appendChild(tot);
      var toggle=function(){ open=(open===key)?null:key; render(); };
      tr.addEventListener('click', toggle);
      tr.addEventListener('keydown', function(e){ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); toggle(); } });
      body.appendChild(tr);
      if(open===key) body.appendChild(detail(t));
    });
    $('empty').hidden=list.length>0;
    $('count').textContent=list.length+' of '+all.length+' teams';
  }
  function setCat(c){
    cat=c; open=null; zoneSel=null;
    var tabs=$('tabs'); tabs.innerHTML='';
    R.categories.concat(R.categories.map(function(g){return g+' players';})).forEach(function(x){
      var b=el('button','',x); b.setAttribute('role','tab'); b.setAttribute('aria-selected', x===c);
      b.onclick=function(){ setCat(x); }; tabs.appendChild(b);
    });
    fillFilters(); render();
  }
  function pick(id){
    R=D.rankings.filter(function(r){return r.id===id;})[0] || D.rankings[D.rankings.length-1];
    $('asof').textContent=R.name+' - as of '+R.date+(R.description?' · '+R.description:'');
    var pills=$('pills'); pills.innerHTML=''; pills.hidden=D.rankings.length<2;
    D.rankings.forEach(function(r){ var a=el('a','',r.name); a.href='#'+r.id; a.setAttribute('aria-current', r.id===R.id); pills.appendChild(a); });
    var hb=$('how'); hb.hidden=!R.explain; hb.href='how-it-works.html#'+R.id;
    PLAYERS=null; $('q').value=''; setCat(R.categories[0]);
  }
  window.addEventListener('hashchange', function(){ pick(location.hash.slice(1)); });
  $('q').addEventListener('input', render); $('nf').addEventListener('change', render);
  if(!D.rankings.length){ $('asof').textContent='No rankings published yet.'; return; }
  pick(location.hash.slice(1));
})();
</script>
</body>
</html>
"""
