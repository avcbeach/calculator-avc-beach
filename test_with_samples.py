"""
Quick sanity test using the three real sample files the user provided.
Run: python3 test_with_samples.py
"""
import sys
from datetime import date
from collections import Counter

from vis_parser import parse_player_career, parse_tournament_list, parse_tournament_entry_list
from classification import classify_tournament, DEFAULT_TEMPLATE
from scoring_engine import score_player

SAMPLE_DIR = "data"


def load(name):
    with open(f"{SAMPLE_DIR}/{name}", encoding="utf-8") as f:
        return f.read()


def main():
    # --- 1. tournament list: build Code -> (type, organizer, country) lookup
    tlist_xml = load("Responses_tournament_list.txt")
    tournaments = parse_tournament_list(tlist_xml)
    print(f"Parsed {len(tournaments)} tournaments from tournament list")

    lookup = {t["code"]: t for t in tournaments}

    # classify every tournament & report bucket distribution + unclassified rate
    buckets = Counter()
    for t in tournaments:
        cls = classify_tournament(t["type"], t["organizer_code"], t["country_code"], avc_country_codes=set())
        buckets[(cls.side, cls.bucket)] += 1
    print("\nClassification distribution across all 9276 sample tournaments:")
    for k, v in sorted(buckets.items(), key=lambda x: -x[1]):
        print(f"  {k[0]:12s} {k[1]:20s} {v}")

    total = sum(buckets.values())
    unclassified = sum(v for k, v in buckets.items() if k[0] == "UNCLASSIFIED")
    print(f"\nUnclassified: {unclassified}/{total} = {unclassified/total:.1%}")

    # --- 2. player career (Xia Xinyi, No=141784)
    player_xml = load("Responses.txt")
    career = parse_player_career(player_xml, "141784")
    print(f"\nParsed {len(career)} career results for player 141784 (Xia Xinyi)")

    # merge organizer_code from tournament list lookup (GetPlayer rows lack it)
    for r in career:
        t = lookup.get(r.tournament_code)
        if t:
            r.organizer_code = t["organizer_code"]
            if not r.country_code:
                r.country_code = t["country_code"]

    # score as of the Yunyang Open (2026-06-18 start main draw) using Entry Point cutoff (-35d)
    yunyang_start = date(2026, 6, 18)
    entry_cutoff = date(2026, 5, 14)  # 35 days before, matches earlier example
    score = score_player(career, entry_cutoff, DEFAULT_TEMPLATE, avc_country_codes=set())

    print(f"\n--- Entry point score for Xia Xinyi as of {entry_cutoff} ---")
    print("FIVB side selected:")
    for r in score.fivb_selected:
        print(f"  {r.end_date} {r.tournament_name[:40]:40s} rank={r.rank} pts={r.points} bucket={r.bucket}")
    print(f"  FIVB total: {score.fivb_total}")
    print("AVC side selected:")
    for r in score.avc_selected:
        print(f"  {r.end_date} {r.tournament_name[:40]:40s} rank={r.rank} pts={r.points} bucket={r.bucket}")
    print(f"  AVC total: {score.avc_total}")
    print(f"TOTAL: {score.total}")
    print(f"\nUnclassified rows for this player in window: {len(score.unclassified)}")
    for r in score.unclassified:
        print(f"  {r.tournament_code} {r.tournament_name} type={r.tournament_type} org={r.organizer_code}")

    # --- 3. event / entry list parse
    event_xml = load("Responses_event.txt")
    parsed_event = parse_tournament_entry_list(event_xml)
    ev = parsed_event["event"]
    print(f"\n--- Event parse: {ev['name']} ({ev['code']}) ---")
    print(f"  Type={ev['type']} Organizer={ev['organizer_code']} Country={ev['country_code']}")
    print(f"  EntryPointsDayOffset={ev['entry_points_day_offset']} SeedPointsDayOffset={ev['seed_points_day_offset']}")
    print(f"  Teams parsed: {len(parsed_event['teams'])}")
    for t in parsed_event["teams"][:3]:
        print(f"    {t['name']}: P1={t['player1_name']}({t['player1_no']}) P2={t['player2_name']}({t['player2_no']})")


if __name__ == "__main__":
    main()
