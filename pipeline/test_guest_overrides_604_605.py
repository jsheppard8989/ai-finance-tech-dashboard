"""Oct 21 2026: cards 604/605 guest/host overrides survive a re-export."""
import export_data


def test_604_605_overrides():
    mc = {"insights": [{"id": 604, "guest_name": None},
                       {"id": 605, "guest_name": "Is The AI Trade Over?"}]}
    guests = [{"name": "Is The AI Trade Over?"}, {"name": "Evan Conrad"}]
    mc, guests = export_data._apply_guest_export_overrides(mc, guests)
    a, b = mc["insights"]
    assert (a["guest_name"], a["guest_org"]) == ("Evan Conrad", "SF Compute")
    assert b["guest_name"] is None and b["host_name"] == "Jack Farley"
    assert [g["name"] for g in guests] == ["Evan Conrad"]
