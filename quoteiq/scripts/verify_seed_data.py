"""Check the QuoteIQ seed data against the example emails' expected outcomes.

Runs the ERP code asset's own search and pricing over products.csv, checks the
catalogue as a whole, then plays every line of every example email with the
query an ideal agent would send (test-data/expected-outcomes.json) and checks
the expected outcome. Exits non-zero on any failure.

    python3 quoteiq/scripts/verify_seed_data.py
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "code-assets" / "erp-query"
EXPECTED = ROOT / "test-data" / "expected-outcomes.json"
EMAILS = ROOT / "test-data" / "emails"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


erp = load_module("erp_query", ASSET / "main.py")
gen = load_module("generate_products", ROOT / "scripts" / "generate_products.py")

failures: list[str] = []


def check(ok: bool, message: str) -> bool:
    print(f"  {'ok  ' if ok else 'FAIL'} {message}")
    if not ok:
        failures.append(message)
    return ok


# ---------------------------------------------------------------- record consistency

NAME_COLOUR = re.compile(r"Colour (\w+)")
NAME_OD = re.compile(r"OD (\d+\.\d+) mm")
M22759_PN = re.compile(r"^M22759/16-(\d+)-(\d)$")


def signature(p: dict) -> str:
    """Everything that describes the product, so search results and full records compare equal."""
    skip = {"sku"} | erp.ADMIN_FIELDS
    return json.dumps({k: v for k, v in p.items() if k not in skip}, sort_keys=True)


def record_problems(p: dict, by_signature: dict[str, list[str]]) -> list[str]:
    """What an attentive reader would notice is wrong with one ERP record."""
    problems = []
    code = p.get("colour_code")
    if code:
        expected = gen.COLOURS[code]
        if p.get("product_color") != expected:
            problems.append(f"Product Color is {p['product_color']} but colour code {code} is {expected}")
        m = NAME_COLOUR.search(p["name"])
        if m and m.group(1) != expected:
            problems.append(f"name says {m.group(1)} but colour code {code} is {expected}")
    if (p.get("sale_description") or "") != (p.get("purchase_description") or ""):
        problems.append("sale and purchase descriptions differ")
    m = NAME_OD.search(p["name"])
    if m and p.get("diameter_mm") is not None and abs(float(m.group(1)) - p["diameter_mm"]) > 0.05:
        problems.append(f"name says OD {m.group(1)} mm but Diameter is {p['diameter_mm']}")
    pn = p.get("standard_part_number")
    if pn:
        m = M22759_PN.match(pn)
        if not m:
            problems.append(f"unreadable standard part number {pn}")
        else:
            if int(m.group(1)) != p.get("awg"):
                problems.append(f"{pn} says {m.group(1)} AWG but AWG is {p.get('awg')}")
            if m.group(2) != code:
                problems.append(f"{pn} says colour {m.group(2)} but colour code is {code}")
    twins = [s for s in by_signature[signature(p)] if s != p["sku"]]
    if twins:
        problems.append(f"identical to {', '.join(twins)}")
    return problems


# ---------------------------------------------------------------- helpers


def search(products, query, limit=50):
    result = erp.run({"operation": "search_products", **query, "limit": limit}, products)
    if "error" in result:
        raise RuntimeError(f"search {query} failed: {result['error']}")
    return result


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        r = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = sum((a - mx) ** 2 for a in rx) ** 0.5
    sy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (sx * sy)


def short(p: dict) -> str:
    return f"{p['sku']} {p['name'][:70]}"


# ---------------------------------------------------------------- catalogue checks


def check_catalogue(products: list[dict], expected: dict, by_signature: dict) -> None:
    print("\nCatalogue")
    families: dict[str, int] = {}
    for p in products:
        families[p["product_family"]] = families.get(p["product_family"], 0) + 1
    print(f"  {len(products)} products: " + ", ".join(f"{k} {v}" for k, v in families.items()))
    check(100 <= len(products) <= 140, f"about 120 products ({len(products)})")

    skus = [p["sku"] for p in products]
    check(len(set(skus)) == len(skus), "SKUs are unique")
    check(all(re.fullmatch(r"FW-\d{5}", s) for s in skus), "SKUs follow FW-#####")
    check(all(p["product_family"] in {"Hook-up wire", "Airframe wire", "High-voltage wire",
                                      "Multi-core cable", "Data cable", "Tape"} for p in products),
          "every product is in one of the six families")

    # The known ERP data issues, and nothing else.
    planned: set[str] = set()
    for item in expected["known_data_issues"]:
        hits = search(products, item["query"])["products"]
        check(len(hits) == item["count"], f"known data issue present: {item['why']} ({len(hits)} record(s))")
        planned.update(p["sku"] for p in hits)
    found = {p["sku"]: record_problems(p, by_signature) for p in products}
    found = {sku: probs for sku, probs in found.items() if probs}
    for sku in sorted(found):
        print(f"       {sku}: {'; '.join(found[sku])}")
    check(set(found) == planned, f"only the known records are inconsistent ({len(found)} found, {len(planned)} known)")

    moqs = [p["moq"] for p in products]
    check(all(gen.MOQ_MIN <= m <= gen.MOQ_MAX for m in moqs),
          f"MoQ between {gen.MOQ_MIN} and {gen.MOQ_MAX} (range {min(moqs)}-{max(moqs)})")
    rho = spearman([p["unit_price"] for p in products], moqs)
    check(rho < -0.8, f"costlier products have lower MoQ (rank correlation {rho:.2f})")

    bad_breaks = []
    for p in products:
        b = p["price_breaks"]
        qty = [x["min_qty"] for x in b]
        pct = [x["discount_pct"] for x in b]
        ok = (len(b) == 3 and p["moq"] < qty[0] < qty[1] < qty[2]
              and 2 <= pct[0] <= 4 and 5 <= pct[1] <= 7 and 8 <= pct[2] <= 12)
        if not ok:
            bad_breaks.append(p["sku"])
    check(not bad_breaks, f"three rising breaks above the MoQ, discounts 2-4 / 5-7 / 8-12% {bad_breaks or ''}")

    leads = [p["lead_time_days"] for p in products]
    check(all(14 <= d <= 56 for d in leads), f"lead time 2-8 weeks (range {min(leads)}-{max(leads)} days)")
    hv = [p["lead_time_days"] for p in products if p["product_family"] == "High-voltage wire"]
    rest = [p["lead_time_days"] for p in products if p["product_family"] == "Hook-up wire"]
    check(sum(hv) / len(hv) > sum(rest) / len(rest),
          f"high-voltage wire takes longer (average {sum(hv) / len(hv):.0f} vs hook-up {sum(rest) / len(rest):.0f} days)")

    airframe = [p for p in products if p["product_family"] == "Airframe wire"]
    off_sheet = []
    for p in airframe:
        stranding, od_min, od_max, _ = gen.M22759_16[p["awg"]]
        if not (p["stranding"] == stranding and od_min * 25.4 - 0.01 <= p["diameter_mm"] <= od_max * 25.4 + 0.01
                and p["voltage_rating_v"] == 600 and p["temp_min_c"] == -55 and p["temp_max_c"] == 150
                and p["insulation"] == "ETFE" and p["plating"] == "tin"):
            off_sheet.append(p["sku"])
    check(not off_sheet, f"M22759/16 rows match the slash-sheet table {off_sheet or ''}")
    check(not any(p["awg"] == 6 for p in airframe), "no 6 AWG M22759/16 (Example 7)")

    folded = [p for p in products if "\n" in (p["sale_description"] or "")]
    check(len(folded) >= 15, f"continuation rows folded into their product ({len(folded)} products)")


# ---------------------------------------------------------------- examples


def rfq_status(outcomes: list[str]) -> str:
    if any(o in {"not_in_catalogue", "erp_record_inconsistent"} for o in outcomes):
        return "Escalated"
    if "needs_clarification" in outcomes:
        return "Need customer clarification"
    return "Success"


def play_line(products, line, by_signature) -> str:
    result = search(products, line["query"])
    hits = result["products"]
    if result["total"] == 0:
        outcome = "not_in_catalogue"
    elif result["total"] == 1:
        outcome = "erp_record_inconsistent" if record_problems(hits[0], by_signature) else "matched"
    elif len({signature(p) for p in hits}) == 1:
        outcome = "erp_record_inconsistent"
    else:
        outcome = "needs_clarification"

    check(outcome == line["expected"], f"{line['ref']}: {outcome}")

    if outcome == "matched":
        p = hits[0]
        priced = erp.run({"operation": "get_price", "sku": p["sku"],
                          "quantities": line["quantities"] or None}, products)
        parts = []
        for q in priced["prices"]:
            asked = q["requested_qty"] if q["requested_qty"] is not None else "none"
            moq = " (MoQ applied)" if q["moq_applied"] else ""
            parts.append(f"{asked} -> {q['quoted_qty']} m{moq} at {q['net_unit_price']} "
                         f"(-{q['discount_pct']:g}%) = {q['line_total']} {priced['currency']}")
        print(f"         {short(p)}")
        print(f"         MoQ {priced['moq']}, lead time {priced['lead_time_days']} days; " + "; ".join(parts))
        if "moq_applied" in line:
            applied = all(q["moq_applied"] for q in priced["prices"])
            none = not any(q["moq_applied"] for q in priced["prices"])
            want = line["moq_applied"]
            reason = ("no quantity given" if not line["quantities"] else "below the MoQ") if want else "requested quantity"
            check(applied if want else none, f"quoted at {'MoQ' if want else 'the requested quantity'} ({reason})")
        if line.get("distinct_prices"):
            nets = [q["net_unit_price"] for q in priced["prices"]]
            check(len(set(nets)) == len(nets), f"each quantity gets its own price ({nets})")
    elif outcome == "needs_clarification":
        print(f"         {result['total']} candidates")
        for field in line.get("differ_on", []):
            values = sorted({str(p.get(field)) for p in hits})
            check(len(values) > 1, f"candidates differ on {field}: {', '.join(values)}")
    elif outcome == "erp_record_inconsistent":
        for p in hits:
            print(f"         {short(p)}")
            print(f"         problem: {'; '.join(record_problems(p, by_signature))}")
    elif outcome == "not_in_catalogue" and "nearest_query" in line:
        asked = int(line["query"]["standard_part_number"].split("-")[1])
        near = search(products, line["nearest_query"])["products"]
        nearest = min(near, key=lambda p: (abs(p["awg"] - asked), p["awg"])) if near else None
        check(nearest is not None and nearest["awg"] == line["nearest_awg"],
              f"nearest product is {line['nearest_awg']} AWG: {short(nearest) if nearest else 'none'}")
    return outcome


def check_examples(products, expected, by_signature) -> None:
    for email in expected["emails"]:
        path = EMAILS / email["file"]
        print(f"\n{email['file']}")
        check(path.exists(), "email file exists")
        if email.get("expected_greeting"):
            # "Dear Mr Iyer," needs "Mr" and "Iyer" in the email: titles come only from the sender.
            addressee = email["expected_greeting"].removeprefix("Dear ").rstrip(",")
            text = path.read_text(encoding="utf-8")
            check(all(word in text for word in addressee.split()),
                  f"greeting {email['expected_greeting']!r} is supported by the email")
        outcomes = [play_line(products, line, by_signature) for line in email["lines"]]
        status = rfq_status(outcomes)
        check(status == email["expected_status"], f"status: {status}")


def check_sandbox_entry(products) -> None:
    """Run the asset the way the sandbox does: JSON on stdin, JSON on stdout."""
    print("\nCode asset entry point")
    request = json.dumps({"operation": "get_product", "sku": products[0]["sku"]})
    proc = subprocess.run([sys.executable, str(ASSET / "main.py")], input=request,
                          capture_output=True, text=True, timeout=30)
    try:
        answer = json.loads(proc.stdout)
    except json.JSONDecodeError:
        answer = {}
    check(answer.get("product", {}).get("sku") == products[0]["sku"], "stdin -> stdout round trip")
    bad = erp.run({"operation": "search_products", "colour": "red"}, products)
    check("error" in bad, f"unknown filter alone is refused: {bad.get('error')}")
    values = erp.run({"operation": "list_values", "field": "plating"}, products)
    check(values.get("values") == ["nickel", "silver", "tin"], f"list_values plating: {values.get('values')}")


def main() -> int:
    products = erp.load_products()
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    by_signature: dict[str, list[str]] = {}
    for p in products:
        by_signature.setdefault(signature(p), []).append(p["sku"])

    check_catalogue(products, expected, by_signature)
    check_examples(products, expected, by_signature)
    check_sandbox_entry(products)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("All checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
