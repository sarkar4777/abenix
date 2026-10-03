"""Create a decision for the load run: v1 in force, v2 approved and ready to publish mid-run. Prints key and token."""

from __future__ import annotations

import json
import os
import sys
import uuid

import httpx

BASE = os.environ.get("BASE", "http://abenix-api:8000")
EMAIL = os.environ.get("AF_EMAIL", "admin@abenix.dev")
PASSWORD = os.environ.get("AF_PASSWORD", "Admin123456")

RULES = [
    {
        "ruleKey": "load.freight.remote",
        "requiresFacts": [
            "shipment.date",
            "shipment.postcode",
            "shipment.weightKg",
        ],
        "when": {
            "all": [
                {"gte": [{"fact": "shipment.date"}, "2026-01-01"]},
                {"inReferenceSet": [{"fact": "shipment.postcode"}, "REMOTE_POSTCODES"]},
                {"gt": [{"fact": "shipment.weightKg"}, 50]},
            ]
        },
        "then": {"surcharge": "REMOTE_AREA_SURCHARGE"},
    },
    {
        "ruleKey": "load.freight.none",
        "when": {"all": []},
        "then": {"surcharge": "NONE"},
    },
]

c = httpx.Client(base_url=BASE, timeout=60)
tok = c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()[
    "data"
]["access_token"]
H = {"Authorization": f"Bearer {tok}"}
if c.get("/api/decision-reference-sets/REMOTE_POSTCODES", headers=H).status_code == 404:
    c.post(
        "/api/decision-reference-sets",
        headers=H,
        json={
            "key": "REMOTE_POSTCODES",
            "name": "Remote postcodes",
            "values": ["HS2", "IV27", "ZE2"],
        },
    )
key = f"load.freight.{uuid.uuid4().hex[:6]}"
r = c.post(
    "/api/decisions",
    headers=H,
    json={"name": "Load test surcharge", "key": key, "rules": RULES},
)
if r.status_code != 201:
    sys.exit(f"create failed: {r.text}")
c.post(f"/api/decisions/{key}/versions/1/propose", headers=H, json={})
p = c.post(f"/api/decisions/{key}/versions/1/publish", headers=H, json={})
if p.status_code != 200:
    sys.exit(f"publish v1 failed: {p.text}")
d = c.post(f"/api/decisions/{key}/versions", headers=H, json={}).json()["data"]
doc = d["authoring"]
doc["rules"][0]["when"]["all"][2]["value"] = 100
c.put(
    f"/api/decisions/{key}/versions/2",
    headers={**H, "If-Match": d["etag"]},
    json={"authoring": doc},
)
pr = c.post(f"/api/decisions/{key}/versions/2/propose", headers=H, json={})
if pr.status_code != 200 or pr.json()["data"]["state"] != "approved":
    sys.exit(f"v2 not approved: {pr.text}")
print(json.dumps({"key": key, "token": tok}))
