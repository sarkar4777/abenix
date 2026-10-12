"""Asset registry: field validation, CSV import with a preview, and the list filters."""

from __future__ import annotations

import pytest

from app.telemetry import assets as A


def test_clean_normalises_and_explains():
    row = A.clean(
        {
            "display_name": " Excavator EX1 ",
            "type": "Machine",
            "tags": ["North Pit", "north pit", "earthworks"],
            "location": {"x": "120.5", "y": 48, "label": "bay 3"},
            "fields": {"Serial": "EX1-2291", "model": "CAT 336", "empty": ""},
        }
    )
    assert row == {
        "display_name": "Excavator EX1",
        "asset_type": "machine",
        "tags": ["north pit", "earthworks"],
        "location": {"x": 120.5, "y": 48.0, "label": "bay 3"},
        "fields": {"serial": "EX1-2291", "model": "CAT 336"},
    }


@pytest.mark.parametrize(
    "body,field",
    [
        ({"type": "boat"}, "type"),
        ({"tags": ["ok", "no#hash"]}, "tags"),
        ({"location": {"lat": 91, "lon": 0}}, "location.lat"),
        ({"location": {"lat": 1, "lon": 2, "x": 3}}, "location"),
        ({"fields": {"bad key!": "x"}}, "fields.bad key!"),
        ({"display_name": "x" * 121}, "display_name"),
    ],
)
def test_clean_rejects_per_field(body, field):
    with pytest.raises(A.AssetInvalid) as e:
        A.clean(body)
    assert field in e.value.fields


def test_csv_preview_marks_each_row():
    text = (
        "group,node,device,name,type,tags,team,lat,lon,x,y,vin,plate,serial,model,fuel\n"
        "fleet,van-017,,Van 17,vehicle,deliveries|city,Drivers,51.5,-0.12,,,WF0X,AB12 CDE,,Transit,diesel\n"
        "fleet,van-018,,Van 18,boat,,,,,,,,,,,\n"
        "fleet,van-017,,Van 17 again,vehicle,,,,,,,,,,,\n"
        "fleet,van-019,,,vehicle,,Nobody,,,,,,,,,\n"
    )
    rows, problem = A.parse_csv(text, {"drivers": "t1"}, {"t1"})
    assert problem is None
    assert rows[0]["errors"] == [] and rows[0]["team_id"] == "t1"
    assert rows[0]["fields"] == {
        "vin": "WF0X",
        "plate": "AB12 CDE",
        "model": "Transit",
        "fuel": "diesel",
    }
    assert rows[0]["location"] == {"lat": 51.5, "lon": -0.12}
    assert rows[0]["tags"] == ["deliveries", "city"]
    assert any("Choose vehicle" in e for e in rows[1]["errors"])
    assert rows[2]["errors"] == ["This asset is also on line 2."]
    assert any("No team called" in e for e in rows[3]["errors"])


def test_csv_whole_file_problems():
    assert A.parse_csv("", {}, set())[1].startswith("The file is empty")
    assert "header" in A.parse_csv("name,type\nx,machine\n", {}, set())[1]
    assert (
        A.parse_csv("group,node\n", {}, set())[1]
        == "The file has a header but no rows."
    )


def test_template_round_trips_through_the_parser():
    rows, problem = A.parse_csv(A.template_csv(), {}, set())
    assert problem is None and all(not r["errors"] for r in rows)
    assert rows[0]["location"] == {"x": 120.5, "y": 48.0}


def test_filters_and_facets():
    rows = [
        {
            "key": "g/a/",
            "group": "g",
            "registered": True,
            "display_name": "EX1",
            "type": "machine",
            "tags": ["north"],
            "fields": {"serial": "S1"},
        },
        {
            "key": "g/b/",
            "group": "g",
            "registered": False,
            "display_name": None,
            "type": None,
            "tags": [],
            "fields": {},
        },
    ]

    def m(**k):
        base = {"q": "", "type_": "", "tag": "", "group": "", "status": ""}
        return [r["key"] for r in rows if A.matches(r, **{**base, **k})]

    assert m(type_="machine") == ["g/a/"]
    assert m(tag="North") == ["g/a/"]
    assert m(status="unregistered") == ["g/b/"]
    assert m(q="s1") == ["g/a/"]
    f = A.facets(rows)
    assert (
        f["registered"] == 1 and f["unregistered"] == 1 and f["types"] == {"machine": 1}
    )
