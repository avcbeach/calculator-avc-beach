"""
templates.py
------------
Simple JSON-backed storage for named scoring templates, so the "Best N /
special conditions" can be edited from the Streamlit UI instead of the code.
"""

import json
import os
from classification import DEFAULT_TEMPLATE

STORE_PATH = os.path.join(os.path.dirname(__file__), "templates_store.json")


def load_all() -> dict:
    if not os.path.exists(STORE_PATH):
        data = {DEFAULT_TEMPLATE["name"]: DEFAULT_TEMPLATE}
        save_all(data)
        return data
    with open(STORE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_all(templates: dict):
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(templates, f, ensure_ascii=False, indent=2)


def save_template(template: dict):
    templates = load_all()
    templates[template["name"]] = template
    save_all(templates)


def delete_template(name: str):
    templates = load_all()
    if name in templates and len(templates) > 1:
        del templates[name]
        save_all(templates)


def make_template(name: str, lookback_days: int, fivb_max: int, avc_max: int,
                   avc_multisport_zonal_cap: int, avc_championship_cap: int) -> dict:
    return {
        "name": name,
        "lookback_days": lookback_days,
        # This cap is checked across BOTH sides combined (see scoring_engine.
        # _apply_global_shared_caps) - a multi-sport game can land on either
        # side depending on host country, but the rule limits it in total.
        "global_cap_groups": [
            {"buckets": ["multisport", "zonal"], "limit": avc_multisport_zonal_cap},
        ],
        "fivb_side": {"max_events": fivb_max, "caps": {}},
        "avc_side": {
            "max_events": avc_max,
            "caps": {
                "championship": avc_championship_cap,
            },
            "shared_cap_groups": [],
        },
    }
