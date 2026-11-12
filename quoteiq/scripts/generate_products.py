"""Generate the QuoteIQ mock ERP catalogue: code-assets/erp-query/products.csv.

Deterministic: the same seed always writes the same file. The products the
example emails need are listed explicitly below, next to the example each
one serves. The rest are neighbours that differ in one
attribute, so a search has to use everything the customer stated. Every name,
description and SKU is synthetic.

    python3 quoteiq/scripts/generate_products.py
"""

from __future__ import annotations

import csv
import math
import random
from pathlib import Path

SEED = 20261111
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "code-assets" / "erp-query" / "products.csv"

# MIL-STD-681 single-digit colour code.
COLOURS = {
    "0": "Black", "1": "Brown", "2": "Red", "3": "Orange", "4": "Yellow",
    "5": "Green", "6": "Blue", "7": "Violet", "8": "Grey", "9": "White",
}
PLATING_ABBR = {"silver": "SPC", "tin": "TPC", "nickel": "NPC"}
DENSITY_G_CM3 = {"PTFE": 2.15, "FEP": 2.15, "ETFE": 1.70}
COPPER_G_CM3 = 8.89

# SAE AS22759/16 (M22759/16): AWG -> (stranding, OD min in, OD max in, weight lb/1000 ft),
# as tabulated by SEA Wire (https://www.sea-wire.com/?p=710). Ratings 600 V, -55 to
# +150 C, tin-coated copper, ETFE (Allied Wire product page for M22759/16-20).
# 6 AWG is left out on purpose: Example 7 asks for it and must find nothing.
M22759_16 = {
    24: ("19/36", 0.043, 0.047, 2.57),
    22: ("19/34", 0.050, 0.054, 3.66),
    20: ("19/32", 0.058, 0.062, 5.36),
    18: ("19/30", 0.069, 0.073, 7.89),
    16: ("19/29", 0.077, 0.081, 9.95),
    14: ("19/27", 0.091, 0.095, 14.9),
    12: ("37/28", 0.111, 0.117, 22.6),
    10: ("37/26", 0.136, 0.142, 35.1),
    8: ("133/29", 0.196, 0.202, 63.5),
}
LB_PER_KFT_TO_G_PER_M = 453.592 / 304.8

FIELDNAMES = [
    "SKU", "Name", "Product Family", "Can be Sold", "Can be Purchased", "Product Type",
    "Internal Product Type", "Sale Description", "Purchase Description", "Unit of Measure",
    "Purchase Unit of Measure", "Product Color", "Routes", "Tracking", "Diameter", "Weight",
    "Remark", "Standard Part Number", "AWG", "Stranding", "Conductor", "Plating", "Insulation",
    "Jacket", "Cores", "Twisted", "Core Colours", "Colour Code", "Voltage Rating (V)",
    "Test Voltage (V)", "Temp Min (C)", "Temp Max (C)", "Corona Resistant", "MoQ",
    "Customer Lead Time (days)", "Sales Price", "Currency",
    "Break 1 Qty", "Break 1 Discount (%)", "Break 2 Qty", "Break 2 Discount (%)",
    "Break 3 Qty", "Break 3 Discount (%)",
]


# ---------------------------------------------------------------- geometry


def strand_mm(gauge: int) -> float:
    return 0.127 * 92 ** ((36 - gauge) / 39)


def split_stranding(stranding: str) -> tuple[int, int]:
    count, gauge = stranding.split("/")
    return int(count), int(gauge)


def copper_g_per_m(stranding: str) -> float:
    count, gauge = split_stranding(stranding)
    return count * math.pi / 4 * strand_mm(gauge) ** 2 * COPPER_G_CM3


def bundle_od_mm(stranding: str) -> float:
    count, gauge = split_stranding(stranding)
    return {7: 3.0, 19: 5.0, 37: 7.0, 133: 15.0}[count] * strand_mm(gauge)


def wire_weight(stranding: str, od: float, insulation: str) -> float:
    dc = bundle_od_mm(stranding)
    insulation_g = math.pi / 4 * max(od**2 - dc**2, 0) * DENSITY_G_CM3[insulation]
    return copper_g_per_m(stranding) + insulation_g


def cable_weight(cores: int, stranding: str, od: float, jacket: str, shield: bool) -> float:
    core_od = bundle_od_mm(stranding) + 0.5
    jacket_g = math.pi / 4 * (od**2 - (od - 0.7) ** 2) * DENSITY_G_CM3[jacket]
    return cores * wire_weight(stranding, core_od, "PTFE") + jacket_g + (3.0 if shield else 0.0)


# ---------------------------------------------------------------- catalogue


def base(**kw) -> dict:
    product = {
        "family": "", "awg": None, "stranding": "", "conductor": "Copper", "plating": "",
        "insulation": "", "jacket": "", "cores": 1, "twisted": False, "core_colours": "",
        "colour_code": "", "product_color": "", "voltage": None, "test_voltage": None,
        "tmin": None, "tmax": None, "corona": False, "od": None, "weight": None,
        "std_pn": "", "uom": "meter", "name": "", "sale": "", "extra": [], "remark": "",
        "price_basis": 0.0, "problem": None, "large": False,
    }
    product.update(kw)
    return product


def hookup(awg, stranding, od, code, voltage, plating="silver", insulation="PTFE",
           tmin=-65, tmax=200, heavy=False, factor=1.0, problem=None) -> dict:
    colour = COLOURS[code]
    wall = ", Heavy Wall" if heavy else ""
    weight = round(wire_weight(stranding, od, insulation), 1)
    test = {250: 1000, 600: 2000, 1000: 3000}[voltage]
    name = (f"{awg} AWG ({stranding}) {PLATING_ABBR[plating]} Conductor, {insulation} Insulation{wall}, "
            f"{voltage} V, {tmin} to {tmax}°C, Colour {colour}, OD {od:.2f} mm")
    sale = (f"Hook-up wire, {awg} AWG ({stranding}) {plating}-plated copper conductor, extruded "
            f"{insulation} insulation{wall.lower()}. Rated {voltage} V, {tmin} °C to +{tmax} °C. "
            f"Colour {colour}. Nominal OD {od:.2f} mm, approx. weight {weight} g/m.")
    return base(family="Hook-up wire", awg=awg, stranding=stranding, plating=plating,
                insulation=insulation, colour_code=code, product_color=colour, voltage=voltage,
                test_voltage=test, tmin=tmin, tmax=tmax, od=od, weight=weight, name=name, sale=sale,
                price_basis=(0.18 + 0.075 * copper_g_per_m(stranding)) * factor, problem=problem)


def airframe(awg, code, problem=None) -> dict:
    stranding, od_min, od_max, lb = M22759_16[awg]
    od = round((od_min + od_max) / 2 * 25.4, 2)
    weight = round(lb * LB_PER_KFT_TO_G_PER_M, 1)
    colour = COLOURS[code]
    pn = f"M22759/16-{awg}-{code}"
    name = (f"{pn} Wire, {awg} AWG ({stranding}) TPC Conductor, ETFE Insulation, 600 V, "
            f"-55 to 150°C, Colour {colour}, OD {od:.2f} mm")
    sale = (f"Airframe wire to SAE AS22759/16, {awg} AWG ({stranding}) tin-coated copper conductor, "
            f"extruded ETFE insulation. Rated 600 V, -55 °C to +150 °C. Colour {colour}. "
            f"OD {od_min * 25.4:.2f} to {od_max * 25.4:.2f} mm, approx. weight {weight} g/m.")
    return base(family="Airframe wire", awg=awg, stranding=stranding, plating="tin",
                insulation="ETFE", colour_code=code, product_color=colour, voltage=600,
                tmin=-55, tmax=150, od=od, weight=weight, std_pn=pn, name=name, sale=sale,
                price_basis=(0.15 + 0.07 * copper_g_per_m(stranding)) * 0.95,
                large=awg <= 10, problem=problem)


def high_voltage(awg, stranding, kv, test_kv, insulation, plating, corona, tmin, tmax, od, code) -> dict:
    colour = COLOURS[code]
    weight = round(wire_weight(stranding, od, insulation), 1)
    tag = ", Corona Resistant" if corona else ""
    name = (f"HV Wire {awg} AWG ({stranding}) {PLATING_ABBR[plating]}, {insulation} Insulation, "
            f"{kv} kV / {test_kv} kV Test{tag}, {tmin} to {tmax}°C, Colour {colour}, OD {od:.2f} mm")
    sale = (f"High-voltage lead wire, {awg} AWG ({stranding}) {plating}-plated copper conductor, "
            f"{insulation} insulation. Operating voltage {kv} kV, test voltage {test_kv} kV, "
            f"{tmin} °C to +{tmax} °C. Colour {colour}. Nominal OD {od:.2f} mm.")
    extra = ([f"Corona and partial-discharge resistant: inception above {kv + 1.5:g} kV."] if corona
             else ["Not partial-discharge rated; for use without corona exposure."])
    factor = ({5: 0.85, 6: 1.0, 10: 1.35}[kv] * (1.0 if corona else 0.8)
              * (1.1 if plating == "nickel" else 1.0))
    return base(family="High-voltage wire", awg=awg, stranding=stranding, plating=plating,
                insulation=insulation, colour_code=code, product_color=colour, voltage=kv * 1000,
                test_voltage=test_kv * 1000, tmin=tmin, tmax=tmax, corona=corona, od=od,
                weight=weight, name=name, sale=sale, extra=extra,
                price_basis=(3.2 + 0.1 * copper_g_per_m(stranding)) * factor)


def multicore(cores, awg, stranding, twisted, shield, jacket, od, core_colours, code) -> dict:
    colour = COLOURS[code]
    lay = ("Twisted Pair" if cores == 2 else "Twisted") if twisted else "Parallel"
    shield_name = ", SPC Braid Shield" if shield else ""
    weight = round(cable_weight(cores, stranding, od, jacket, shield), 1)
    name = (f"{cores}C {awg} AWG ({stranding}) SPC, PTFE Insulated Cores, {lay}{shield_name}, "
            f"{jacket} Jacket, Colour {colour}, OD {od:.2f} mm")
    sale = (f"Multi-core cable, {cores} cores of {awg} AWG ({stranding}) silver-plated copper with PTFE "
            f"insulation, {'twisted' if twisted else 'laid parallel'}"
            f"{', silver-plated copper braid shield' if shield else ''}, {jacket} jacket, colour {colour}. "
            f"Rated 600 V, -65 °C to +200 °C. Nominal OD {od:.2f} mm.")
    core_names = ", ".join(COLOURS[c] for c in core_colours.split("/"))
    single = 0.18 + 0.075 * copper_g_per_m(stranding)
    return base(family="Multi-core cable", awg=awg, stranding=stranding, plating="silver",
                insulation="PTFE", jacket=jacket, cores=cores, twisted=twisted,
                core_colours=core_colours, colour_code=code, product_color=colour, voltage=600,
                test_voltage=2000, tmin=-65, tmax=200, od=od, weight=weight, name=name, sale=sale,
                extra=[f"Core colours: {core_names}."],
                price_basis=cores * single * 1.2 + 0.9 + (1.3 if shield else 0.0))


def data_cable(pairs, awg, stranding, shield, ohms, code, od, price) -> dict:
    colour = COLOURS[code]
    weight = round(cable_weight(pairs * 2, stranding, od, "FEP", "Braid" in shield), 1)
    name = (f"{pairs}-Pair {awg} AWG ({stranding}) SPC Data Cable, PTFE Insulation, {shield}, "
            f"FEP Jacket, {ohms} Ohm, Colour {colour}, OD {od:.2f} mm")
    sale = (f"Data cable, {pairs} twisted pair{'s' if pairs > 1 else ''} of {awg} AWG ({stranding}) "
            f"silver-plated copper with PTFE insulation, {shield.lower()}, FEP jacket, colour {colour}. "
            f"Rated 300 V, -65 °C to +200 °C. Nominal OD {od:.2f} mm.")
    electrical = {
        100: "Characteristic impedance 100 ±15 ohm; capacitance 46 pF/m nominal; velocity of propagation 72%.",
        120: "Characteristic impedance 120 ±12 ohm; capacitance 39 pF/m nominal; velocity of propagation 75%.",
    }[ohms]
    return base(family="Data cable", awg=awg, stranding=stranding, plating="silver",
                insulation="PTFE", jacket="FEP", cores=pairs * 2, twisted=True, colour_code=code,
                product_color=colour, voltage=300, test_voltage=1500, tmin=-65, tmax=200, od=od,
                weight=weight, name=name, sale=sale, extra=[electrical], price_basis=price)


def tape(kind, thickness, width, colour, price) -> dict:
    name = f"PTFE {kind} Tape {thickness:.2f} mm x {width} mm, {colour}"
    sale = (f"PTFE {kind.lower()} tape, {thickness:.2f} mm thick, {width} mm wide, colour "
            f"{colour.lower()}. Supplied on cores, sold by weight.")
    return base(family="Tape", conductor="", cores=None, product_color=colour, uom="kg",
                name=name, sale=sale, price_basis=price)


def catalogue() -> list[dict]:
    products: list[dict] = []

    # 600 V silver-plated PTFE hook-up wire. Examples 1 (lines 2-3), 2, 4 and 6.
    for awg, stranding, od, codes, heavy in [
        (30, "7/38", 0.86, "029", False),
        (28, "7/36", 0.97, "0296", False),
        (26, "7/34", 1.10, "09256", False),   # Example 1 line 2
        (26, "7/34", 1.40, "0925", True),     # Example 1 line 3: same wire, heavier wall
        (24, "19/36", 1.20, "02964", False),  # Example 2
        (24, "7/32", 1.22, "09", False),
        (22, "19/34", 1.37, "02956", False),
        (20, "19/32", 1.57, "0296", False),
        (18, "19/30", 1.83, "029", False),
        (16, "19/29", 2.20, "029", False),    # Example 4
        (14, "19/27", 2.60, "029", False),    # Example 4
        (12, "37/28", 3.05, "02", False),
    ]:
        for code in codes:
            products.append(hookup(awg, stranding, od, code, 600, heavy=heavy,
                                   factor=1.15 if heavy else 1.0))

    # 1000 V. Example 1 line 1 is the 22 AWG row.
    for awg, stranding, od, codes in [
        (26, "19/38", 1.32, "029"),
        (24, "19/36", 1.47, "029"),
        (22, "19/34", 1.63, "02596"),
        (20, "19/32", 1.83, "029"),
        (18, "19/30", 2.08, "02"),
    ]:
        for code in codes:
            products.append(hookup(awg, stranding, od, code, 1000, factor=1.25))

    # 250 V thin wall. The 28 AWG white record's two descriptions disagree on colour.
    for awg, stranding, od in [(30, "7/38", 0.61), (28, "7/36", 0.71), (26, "7/34", 0.81), (24, "19/36", 0.97)]:
        for code in "09":
            problem = "purchase_colour" if (awg, code) == (28, "9") else None
            products.append(hookup(awg, stranding, od, code, 250, factor=0.85, problem=problem))

    # Nickel-plated, 260 C. The 20 AWG red record is duplicated below.
    for awg, stranding, od, codes in [(22, "19/34", 1.37, "09"), (20, "19/32", 1.57, "02"), (18, "19/30", 1.83, "09")]:
        for code in codes:
            problem = "duplicate" if (awg, code) == (20, "2") else None
            products.append(hookup(awg, stranding, od, code, 600, plating="nickel", tmax=260,
                                   factor=1.45, problem=problem))

    # FEP over tin-plated copper, 150 C. The 20 AWG black record's diameter field disagrees with its name.
    for awg, stranding, od, codes in [(24, "19/36", 1.20, "09"), (22, "19/34", 1.37, "02"), (20, "19/32", 1.52, "06")]:
        for code in codes:
            problem = "diameter_field" if (awg, code) == (20, "0") else None
            products.append(hookup(awg, stranding, od, code, 600, plating="tin", insulation="FEP",
                                   tmax=150, factor=0.8, problem=problem))

    # M22759/16. Examples 3 and 7. The 14 AWG white record's colour field says red.
    for awg, codes in [(24, "90"), (22, "0296"), (20, "190"), (18, "20"), (16, "260"),
                       (14, "90"), (12, "40"), (10, "0"), (8, "60")]:
        for code in codes:
            problem = "colour_field" if (awg, code) == (14, "9") else None
            products.append(airframe(awg, code, problem=problem))

    # High-voltage wire. Nickel plating carries the 260 C rating; silver plating
    # stops at 200 C. Example 5 takes the 6 kV corona-resistant nickel rows. The
    # near misses fail on voltage, on corona, or (the silver one) on plating and
    # temperature together.
    for row in [
        (20, "19/32", 6, 20, "PTFE", "nickel", True, -90, 260, 2.40, "29"),
        (18, "19/30", 6, 20, "PTFE", "nickel", True, -90, 260, 2.70, "02"),
        (20, "19/32", 5, 15, "PTFE", "nickel", True, -90, 260, 2.10, "2"),
        (20, "19/32", 6, 20, "PTFE", "nickel", False, -90, 260, 2.40, "2"),
        (18, "19/30", 6, 20, "PTFE", "silver", True, -90, 200, 2.70, "0"),
        (22, "19/34", 10, 30, "PTFE", "nickel", True, -90, 260, 2.70, "29"),
        (16, "19/29", 10, 30, "PTFE", "nickel", True, -90, 260, 3.40, "0"),
    ]:
        *spec, codes = row
        for code in codes:
            products.append(high_voltage(*spec, code))

    # Multi-core cable. Example 1 line 4 is the first row; each other row differs in one way.
    for row in [
        (2, 24, "7/32", True, False, "PTFE", 3.70, "0/9", "9"),
        (2, 24, "7/32", True, True, "PTFE", 4.30, "0/9", "9"),
        (2, 24, "7/32", True, False, "FEP", 3.70, "0/9", "9"),
        (2, 24, "7/32", False, False, "PTFE", 3.70, "0/9", "9"),
        (2, 24, "19/36", True, False, "PTFE", 3.60, "0/9", "9"),
        (2, 22, "19/34", True, False, "PTFE", 4.10, "0/9", "0"),
        (3, 24, "7/32", True, False, "PTFE", 3.95, "0/2/9", "9"),
        (4, 26, "7/34", True, False, "FEP", 3.80, "0/2/6/9", "6"),
    ]:
        products.append(multicore(*row))

    for row in [
        (4, 24, "19/36", "Foil and SPC Braid Shield", 100, "6", 6.10, 5.6),
        (4, 26, "19/38", "Foil Shield", 100, "9", 5.20, 4.9),
        (2, 24, "19/36", "SPC Braid Shield", 100, "7", 4.60, 3.8),
        (1, 22, "19/34", "SPC Braid Shield", 120, "9", 3.90, 3.1),
    ]:
        products.append(data_cable(*row))

    for row in [("Skived", 0.05, 12, "Natural", 62.0), ("Skived", 0.10, 25, "Natural", 58.0),
                ("Unsintered", 0.08, 10, "White", 71.0), ("Unsintered", 0.08, 6, "Brown", 74.0)]:
        products.append(tape(*row))

    return products


# ---------------------------------------------------------------- commercial terms


def tidy(qty: float) -> int:
    if qty < 100:
        return max(10, int(round(qty / 10)) * 10)
    if qty < 1000:
        return int(round(qty / 50)) * 50
    return int(round(qty / 100)) * 100


def discount_at(breaks: list[tuple[int, int]], qty: float) -> int:
    pct = 0
    for min_qty, d in breaks:
        if qty >= min_qty:
            pct = d
    return pct


def draw_breaks(rng: random.Random, moq: int) -> list[tuple[int, int]] | None:
    b = [tidy(moq * rng.randint(3, 5)), tidy(moq * rng.randint(8, 12)), tidy(moq * rng.randint(20, 30))]
    if not (moq < b[0] < b[1] < b[2]):
        return None
    return list(zip(b, [rng.randint(2, 4), rng.randint(5, 7), rng.randint(8, 12)]))


def make_breaks(rng: random.Random, moq: int, distinct_for: list[int] | None = None) -> tuple[int, list]:
    """Breaks at multiples of the MoQ. With distinct_for, every listed quantity
    must land on a different break, so each gets its own price (Example 5)."""
    candidates = [moq]
    if distinct_for:
        # move the MoQ outward from its drawn value until the breaks can separate the quantities
        candidates = sorted(range(10, min(distinct_for) + 1), key=lambda m: (abs(m - moq), m))
    for m in candidates:
        for _ in range(200):
            breaks = draw_breaks(rng, m)
            if breaks is None:
                continue
            if distinct_for and len({discount_at(breaks, q) for q in distinct_for}) < len(distinct_for):
                continue
            return m, breaks
    raise RuntimeError(f"no breaks for MoQ {moq}")


EXAMPLE_5_QUANTITIES = [100, 500, 1000, 2000]
MOQ_MIN, MOQ_MAX = 10, 100


def is_example_5(p: dict) -> bool:
    return (p["family"] == "High-voltage wire" and p["corona"] and p["insulation"] == "PTFE"
            and p["plating"] == "nickel" and p["voltage"] == 6000
            and (p["awg"], p["colour_code"]) in {(20, "2"), (18, "0")})


def is_example_4(p: dict) -> bool:
    return (p["family"] == "Hook-up wire" and p["voltage"] == 600 and p["plating"] == "silver"
            and (p["awg"], p["stranding"]) in {(14, "19/27"), (16, "19/29")}
            and p["colour_code"] in {"0", "2"})


def assign_commercial_terms(products: list[dict], rng: random.Random) -> None:
    for p in products:
        p["price"] = max(0.15, round(p["price_basis"] * rng.uniform(0.94, 1.06), 2))
    # Costlier products get a lower MoQ: place each product by price rank, then jitter.
    ranked = sorted(range(len(products)), key=lambda i: products[i]["price"])
    for rank, i in enumerate(ranked):
        pct = rank / (len(products) - 1)
        moq = int(round(MOQ_MAX - (MOQ_MAX - MOQ_MIN) * pct + rng.uniform(-8, 8)))
        products[i]["moq_drawn"] = max(MOQ_MIN, min(MOQ_MAX, moq))
    for p in products:
        # Example 4 asks for 21-24 m. Its products' MoQ sits above that, so the
        # below-MoQ rule shows there and nowhere it isn't meant to.
        if is_example_4(p):
            p["moq_drawn"] = max(p["moq_drawn"], rng.randint(30, 50))
        p["moq"], p["breaks"] = make_breaks(
            rng, p["moq_drawn"], EXAMPLE_5_QUANTITIES if is_example_5(p) else None)
        days = rng.randint(14, 42)
        if p["family"] == "High-voltage wire" or p["large"]:
            days = min(56, days + rng.randint(7, 14))
        if p["family"] == "Tape":
            days = rng.randint(14, 21)
        p["lead_time"] = days


# ---------------------------------------------------------------- writing


def apply_problem(p: dict) -> None:
    """Known ERP data issues: records that contradict themselves, which the
    matcher must escalate rather than quote."""
    p["purchase"] = p["sale"]
    if p["problem"] == "purchase_colour":
        p["purchase"] = p["sale"].replace(f"Colour {p['product_color']}.", "Colour Blue.")
    elif p["problem"] == "diameter_field":
        p["diameter_override"] = 1.95
    elif p["problem"] == "colour_field":
        p["product_color"] = "Red"


def fmt_bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def fmt(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:g}" if value != int(value) else f"{value:.1f}"
    return str(value)


def to_row(p: dict) -> dict:
    breaks = p["breaks"]
    row = {
        "SKU": p["sku"], "Name": p["name"], "Product Family": p["family"],
        "Can be Sold": "TRUE", "Can be Purchased": "FALSE", "Product Type": "Stockable Product",
        "Internal Product Type": "FG", "Sale Description": p["sale"],
        "Purchase Description": p["purchase"], "Unit of Measure": p["uom"],
        "Purchase Unit of Measure": p["uom"], "Product Color": p["product_color"],
        "Routes": "Manufacture", "Tracking": "By Lots",
        "Diameter": fmt(p.get("diameter_override", p["od"])), "Weight": fmt(p["weight"]),
        "Remark": p["remark"], "Standard Part Number": p["std_pn"], "AWG": fmt(p["awg"]),
        "Stranding": p["stranding"], "Conductor": p["conductor"], "Plating": p["plating"],
        "Insulation": p["insulation"], "Jacket": p["jacket"], "Cores": fmt(p["cores"]),
        "Twisted": fmt_bool(p["twisted"]) if p["cores"] else "", "Core Colours": p["core_colours"],
        "Colour Code": p["colour_code"], "Voltage Rating (V)": fmt(p["voltage"]),
        "Test Voltage (V)": fmt(p["test_voltage"]), "Temp Min (C)": fmt(p["tmin"]),
        "Temp Max (C)": fmt(p["tmax"]),
        "Corona Resistant": fmt_bool(p["corona"]) if p["family"] != "Tape" else "",
        "MoQ": str(p["moq"]), "Customer Lead Time (days)": str(p["lead_time"]),
        "Sales Price": f"{p['price']:.2f}", "Currency": "USD",
    }
    for n, (qty, pct) in enumerate(breaks, start=1):
        row[f"Break {n} Qty"] = str(qty)
        row[f"Break {n} Discount (%)"] = str(pct)
    return row


def main() -> None:
    rng = random.Random(SEED)
    products = catalogue()
    assign_commercial_terms(products, rng)

    # One record entered twice: same attributes and terms, second SKU.
    original = next(p for p in products if p["problem"] == "duplicate")
    copy = dict(original)
    products.insert(next(i for i, p in enumerate(products) if p["family"] != "Hook-up wire"), copy)

    skus = rng.sample(range(10000, 100000), len(products))
    for p, number in zip(products, skus):
        p["sku"] = f"FW-{number}"
        apply_problem(p)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for p in products:
            writer.writerow(to_row(p))
            # Long descriptions run onto rows without a product, as in the real export.
            for line in p["extra"]:
                writer.writerow({"Sale Description": line, "Purchase Description": line})

    families: dict[str, int] = {}
    for p in products:
        families[p["family"]] = families.get(p["family"], 0) + 1
    print(f"Wrote {len(products)} products to {OUT.relative_to(ROOT.parent)}")
    for family, count in families.items():
        print(f"  {family:<18} {count}")


if __name__ == "__main__":
    main()
