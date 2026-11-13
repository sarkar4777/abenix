"""Mock ERP for the QuoteIQ example.

Reads one JSON request on stdin and writes one JSON answer on stdout. The
products come from products.csv beside this file, so no product data lives in
the code. Operations:

  search_products  structured filters over the catalogue
  get_product      one full record by SKU
  get_price        quoted quantity, MoQ, quantity-break discount, lead time
  list_values      the values a field takes, so callers use the ERP's terms
  price_lines      the pipeline's step after the matcher: every matched line's
                   product and prices taken from the ERP

The model reads the customer's wording and decides the filters. This program
only filters, looks up and does the price arithmetic. A matched line's product
record and prices come from price_lines, not from the matcher's answer, so a
quote's numbers never depend on the model.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parent / "products.csv"

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
DEFAULT_OD_TOLERANCE_MM = 0.1

# CSV header -> record key. Headers follow the ERP export the mock copies.
COLUMNS = {
    "SKU": "sku",
    "Name": "name",
    "Product Family": "product_family",
    "Can be Sold": "can_be_sold",
    "Can be Purchased": "can_be_purchased",
    "Product Type": "product_type",
    "Internal Product Type": "internal_product_type",
    "Sale Description": "sale_description",
    "Purchase Description": "purchase_description",
    "Unit of Measure": "uom",
    "Purchase Unit of Measure": "purchase_uom",
    "Product Color": "product_color",
    "Routes": "routes",
    "Tracking": "tracking",
    "Diameter": "diameter_mm",
    "Weight": "weight_g_per_m",
    "Remark": "remark",
    "Standard Part Number": "standard_part_number",
    "AWG": "awg",
    "Stranding": "stranding",
    "Conductor": "conductor",
    "Plating": "plating",
    "Insulation": "insulation",
    "Jacket": "jacket",
    "Cores": "cores",
    "Twisted": "twisted",
    "Core Colours": "core_colours",
    "Colour Code": "colour_code",
    "Voltage Rating (V)": "voltage_rating_v",
    "Test Voltage (V)": "test_voltage_v",
    "Temp Min (C)": "temp_min_c",
    "Temp Max (C)": "temp_max_c",
    "Corona Resistant": "corona_resistant",
    "MoQ": "moq",
    "Customer Lead Time (days)": "lead_time_days",
    "Sales Price": "unit_price",
    "Currency": "currency",
}
BREAK_COLUMNS = [
    ("Break 1 Qty", "Break 1 Discount (%)"),
    ("Break 2 Qty", "Break 2 Discount (%)"),
    ("Break 3 Qty", "Break 3 Discount (%)"),
]

INT_FIELDS = {
    "awg", "cores", "moq", "lead_time_days", "voltage_rating_v",
    "test_voltage_v", "temp_min_c", "temp_max_c",
}
FLOAT_FIELDS = {"diameter_mm", "weight_g_per_m", "unit_price"}
BOOL_FIELDS = {"can_be_sold", "can_be_purchased", "twisted", "corona_resistant"}

# Bookkeeping fields every product shares. get_product returns them; search
# leaves them out to keep candidate lists short.
ADMIN_FIELDS = {
    "can_be_sold", "can_be_purchased", "product_type", "internal_product_type",
    "purchase_uom", "routes", "tracking",
}

LISTABLE_FIELDS = {
    "product_family", "awg", "stranding", "conductor", "plating", "insulation",
    "jacket", "cores", "colour_code", "core_colours", "voltage_rating_v",
    "test_voltage_v", "temp_min_c", "temp_max_c", "uom", "product_color",
}

SEARCH_FILTERS = {
    "standard_part_number", "product_family", "awg", "stranding", "cores",
    "twisted", "core_colours", "conductor", "plating", "insulation", "jacket",
    "colour_code", "od_mm", "od_tolerance_mm", "min_voltage_v",
    "min_test_voltage_v", "temp_min_c", "temp_max_c", "corona_resistant",
    "text", "limit",
}


class RequestError(Exception):
    """A request the caller can fix. Reported back as {"error": ...}."""


# ---------------------------------------------------------------- loading


def _parse(key: str, raw: str) -> Any:
    value = (raw or "").strip()
    if value == "":
        return None
    if key in INT_FIELDS:
        return int(float(value))
    if key in FLOAT_FIELDS:
        return float(value)
    if key in BOOL_FIELDS:
        return value.upper() == "TRUE"
    return value


def load_products(path: Path = DATA_FILE) -> list[dict[str, Any]]:
    """Read the export. A row without a SKU continues the previous product's
    descriptions, the way long descriptions spill onto extra rows."""
    products: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not (row.get("SKU") or "").strip():
                if products:
                    last = products[-1]
                    for col, key in (("Sale Description", "sale_description"),
                                     ("Purchase Description", "purchase_description")):
                        extra = (row.get(col) or "").strip()
                        if extra:
                            last[key] = f"{last.get(key) or ''}\n{extra}".strip()
                continue
            record = {key: _parse(key, row.get(col, "")) for col, key in COLUMNS.items()}
            breaks = []
            for qty_col, pct_col in BREAK_COLUMNS:
                qty, pct = (row.get(qty_col) or "").strip(), (row.get(pct_col) or "").strip()
                if qty and pct:
                    breaks.append({"min_qty": int(float(qty)), "discount_pct": float(pct)})
            record["price_breaks"] = sorted(breaks, key=lambda b: b["min_qty"])
            products.append(record)
    return products


# ---------------------------------------------------------------- helpers


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "no", "0"}:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise RequestError(f"expected true or false, got {value!r}")


def _as_number(name: str, value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise RequestError(f"{name} must be a number, got {value!r}") from None


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split(",") if v.strip()]


def _norm_pn(value: str) -> str:
    return "".join(str(value).upper().split())


def _colour_set(value: Any) -> set[str]:
    return {c.strip() for c in str(value).replace(",", "/").split("/") if c.strip()}


def _public(product: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in product.items() if k not in ADMIN_FIELDS}


def _find(products: list[dict[str, Any]], sku: Any) -> dict[str, Any]:
    wanted = str(sku or "").strip().upper()
    if not wanted:
        raise RequestError("sku is required")
    for p in products:
        if p["sku"] == wanted:
            return p
    raise RequestError(f"no product with SKU {wanted}")


# ---------------------------------------------------------------- operations


def _matches(p: dict[str, Any], f: dict[str, Any]) -> bool:
    def text_eq(field: str) -> bool:
        return (p.get(field) or "").casefold() == str(f[field]).strip().casefold()

    if "standard_part_number" in f:
        wanted = _norm_pn(f["standard_part_number"])
        have = _norm_pn(p.get("standard_part_number") or "")
        if not have:
            return False
        if wanted.endswith("*"):
            if not have.startswith(wanted[:-1]):
                return False
        elif have != wanted:
            return False
    for field in ("product_family", "stranding", "conductor", "plating", "jacket"):
        if field in f and not text_eq(field):
            return False
    if "insulation" in f:
        allowed = {v.casefold() for v in _as_list(f["insulation"])}
        if (p.get("insulation") or "").casefold() not in allowed:
            return False
    for field in ("awg", "cores"):
        if field in f and p.get(field) != int(_as_number(field, f[field])):
            return False
    if "colour_code" in f and (p.get("colour_code") or "") != str(f["colour_code"]).strip():
        return False
    if "core_colours" in f and _colour_set(p.get("core_colours") or "") != _colour_set(f["core_colours"]):
        return False
    for field in ("twisted", "corona_resistant"):
        if field in f and bool(p.get(field)) != _as_bool(f[field]):
            return False
    if "od_mm" in f:
        od = _as_number("od_mm", f["od_mm"])
        tol = _as_number("od_tolerance_mm", f.get("od_tolerance_mm", DEFAULT_OD_TOLERANCE_MM))
        if p.get("diameter_mm") is None or abs(p["diameter_mm"] - od) > tol + 1e-9:
            return False
    if "min_voltage_v" in f:
        if p.get("voltage_rating_v") is None or p["voltage_rating_v"] < _as_number("min_voltage_v", f["min_voltage_v"]):
            return False
    if "min_test_voltage_v" in f:
        if p.get("test_voltage_v") is None or p["test_voltage_v"] < _as_number("min_test_voltage_v", f["min_test_voltage_v"]):
            return False
    # A temperature range asked for must sit inside the product's rating.
    if "temp_min_c" in f:
        if p.get("temp_min_c") is None or p["temp_min_c"] > _as_number("temp_min_c", f["temp_min_c"]):
            return False
    if "temp_max_c" in f:
        if p.get("temp_max_c") is None or p["temp_max_c"] < _as_number("temp_max_c", f["temp_max_c"]):
            return False
    if "text" in f:
        haystack = " ".join(
            str(p.get(k) or "") for k in ("name", "sale_description", "purchase_description", "standard_part_number")
        ).casefold()
        if not all(word in haystack for word in str(f["text"]).casefold().split()):
            return False
    return True


def search_products(products: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
    filters = {k: v for k, v in args.items() if k in SEARCH_FILTERS and v not in (None, "", [])}
    ignored = sorted(k for k in args if k not in SEARCH_FILTERS and k != "operation")
    limit = int(_as_number("limit", filters.pop("limit", DEFAULT_LIMIT)))
    limit = max(1, min(limit, MAX_LIMIT))
    criteria = {k: v for k, v in filters.items() if k != "od_tolerance_mm"}
    if not criteria:
        raise RequestError(
            "give at least one filter as a top-level key next to operation, e.g. "
            '{"operation": "search_products", "awg": 22, "colour_code": "9"}. '
            f"Received keys: {sorted(args)}"
        )
    hits = sorted((p for p in products if _matches(p, filters)), key=lambda p: (p["name"], p["sku"]))
    out: dict[str, Any] = {
        "operation": "search_products",
        "filters": filters,
        "total": len(hits),
        "returned": min(len(hits), limit),
        "products": [_public(p) for p in hits[:limit]],
    }
    if ignored:
        out["ignored_filters"] = ignored
    return out


def get_product(products: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
    return {"operation": "get_product", "product": _find(products, args.get("sku"))}


def price_line(product: dict[str, Any], requested: float | None) -> dict[str, Any]:
    moq = product["moq"]
    if requested is None:
        quoted, moq_applied = moq, True
    else:
        moq_applied = requested < moq
        quoted = moq if moq_applied else requested
    discount = 0.0
    for brk in product["price_breaks"]:
        if quoted >= brk["min_qty"]:
            discount = brk["discount_pct"]
    net = round(product["unit_price"] * (1 - discount / 100), 4)
    return {
        "requested_qty": requested,
        "quoted_qty": quoted,
        "moq_applied": moq_applied,
        "discount_pct": discount,
        "net_unit_price": net,
        "line_total": round(net * quoted, 2),
    }


def get_price(products: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
    product = _find(products, args.get("sku"))
    if "quantities" in args and args["quantities"] not in (None, []):
        raw = args["quantities"] if isinstance(args["quantities"], list) else [args["quantities"]]
    elif args.get("quantity") not in (None, ""):
        raw = [args["quantity"]]
    else:
        raw = [None]
    quantities = []
    for q in raw:
        if q is None:
            quantities.append(None)
            continue
        value = _as_number("quantity", q)
        if value <= 0:
            raise RequestError("quantity must be above zero")
        quantities.append(int(value) if value == int(value) else value)
    return {
        "operation": "get_price",
        "sku": product["sku"],
        "uom": product["uom"],
        "currency": product["currency"],
        "unit_price": product["unit_price"],
        "moq": product["moq"],
        "price_breaks": product["price_breaks"],
        "lead_time_days": product["lead_time_days"],
        "prices": [price_line(product, q) for q in quantities],
    }


def list_values(products: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
    field = str(args.get("field") or "").strip()
    if field not in LISTABLE_FIELDS:
        raise RequestError(f"field must be one of: {', '.join(sorted(LISTABLE_FIELDS))}")
    values = sorted({p[field] for p in products if p.get(field) is not None}, key=lambda v: (str(type(v)), v))
    return {"operation": "list_values", "field": field, "values": values}


QUOTED_PRODUCT_FIELDS = ("sku", "standard_part_number", "name", "sale_description", "uom")
NEAREST_FIELDS = ("sku", "standard_part_number", "name", "awg")


def _line_answer(item: Any) -> tuple[dict[str, Any] | None, Any]:
    """The matcher's answer inside one line result, and how to put it back.

    A pipeline step's result wraps the answer as {"response": "<json>", "cost": ...}.
    An answer that isn't JSON is left as it is: the decider and the app treat
    it as unreadable.
    """
    if isinstance(item, dict) and "response" in item:
        answer, _ = _line_answer(item["response"])
        if answer is None:
            return None, item
        text = isinstance(item["response"], str)
        return answer, lambda a: {**item, "response": json.dumps(a) if text else a}
    if isinstance(item, str):
        try:
            answer = json.loads(item)
        except ValueError:
            return None, item
        return (answer, json.dumps) if isinstance(answer, dict) else (None, item)
    if isinstance(item, dict):
        return item, lambda a: a
    return None, item


def price_lines(products: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
    """Replace what the matcher reported about products with the ERP's own records.

    A matched line gets the chosen product's record and the prices for the
    quantities the extractor read from the email, whatever the matcher wrote.
    A nearest product the ERP doesn't hold is dropped. A matched line whose SKU
    the ERP doesn't hold is an error: the matcher chose something that doesn't
    exist, and the step fails rather than quote it.
    """
    lines = args.get("lines")
    if not isinstance(lines, list):
        raise RequestError("lines must be the list of the matcher's line results")
    rfq_lines = args.get("rfq_lines")
    if not isinstance(rfq_lines, list):
        raise RequestError("rfq_lines must be the extractor's list of RFQ lines")
    quantities = {
        line.get("line_ref"): line.get("quantities")
        for line in rfq_lines if isinstance(line, dict)
    }
    by_sku = {p["sku"]: p for p in products}
    out = []
    for item in lines:
        answer, put_back = _line_answer(item)
        if answer is None:
            out.append(put_back)
            continue
        ref = answer.get("line_ref")
        if answer.get("outcome") == "matched":
            sku = str((answer.get("product") or {}).get("sku") or "").strip().upper()
            if sku not in by_sku:
                raise RequestError(f"line {ref} was matched to {sku or 'no SKU'}, which the ERP doesn't hold")
            if ref not in quantities:
                raise RequestError(f"line {ref} is not one of the RFQ's lines")
            product = by_sku[sku]
            answer["product"] = {k: product.get(k) for k in QUOTED_PRODUCT_FIELDS}
            answer["pricing"] = get_price(products, {"sku": sku, "quantities": quantities[ref]})
        if isinstance(answer.get("nearest"), list):
            answer["nearest"] = [
                {**entry, **{k: by_sku[s].get(k) for k in NEAREST_FIELDS}}
                for entry in answer["nearest"]
                if isinstance(entry, dict)
                and (s := str(entry.get("sku") or "").strip().upper()) in by_sku
            ]
        out.append(put_back(answer))
    return {"operation": "price_lines", "lines": out}


OPERATIONS = {
    "search_products": search_products,
    "get_product": get_product,
    "get_price": get_price,
    "list_values": list_values,
    "price_lines": price_lines,
}
# Called by the pipeline, not by a model, so no one is there to read an error
# and correct the call: the program exits non-zero and the step fails.
PIPELINE_OPERATIONS = {"price_lines"}


def _flatten(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept the shapes a model tends to send besides the flat one: the whole
    request wrapped again in "input", or the filters nested under "filters"."""
    if isinstance(payload.get("input"), dict) and "operation" not in payload:
        payload = payload["input"]
    if isinstance(payload.get("input"), str) and "operation" not in payload:
        try:
            payload = json.loads(payload["input"])
        except ValueError:
            pass
    nested = payload.get("filters")
    if isinstance(nested, dict):
        payload = {**{k: v for k, v in payload.items() if k != "filters"}, **nested}
    return payload


def run(payload: dict[str, Any], products: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Answer one request. Importable, so tests call the same code the sandbox runs."""
    if not isinstance(payload, dict):
        return {"error": "the request must be a JSON object"}
    payload = _flatten(payload)
    op = payload.get("operation")
    if op not in OPERATIONS:
        return {"error": f"operation must be one of: {', '.join(OPERATIONS)}"}
    try:
        return OPERATIONS[op](products if products is not None else load_products(), payload)
    except RequestError as exc:
        return {"operation": op, "error": str(exc)}


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # noqa: BLE001
        json.dump({"error": f"invalid JSON on stdin: {exc}"}, sys.stdout)
        return
    answer = run(payload)
    json.dump(answer, sys.stdout)
    if answer.get("operation") in PIPELINE_OPERATIONS and "error" in answer:
        sys.exit(1)


if __name__ == "__main__":
    main()
