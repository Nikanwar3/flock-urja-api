import pytest

FAKE_METERS = [
    {
        "meterId": "J100000",
        "serialNo": "SE33962",
        "make": "HPL",
        "phaseType": "single",
        "installStatus": "Installed",
        "installType": "Whole Current",
        "build": "legacy",
        "dtCode": "DT-001",
        "hierarchy": {
            "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
            "circle": {"name": "Circle 1", "code": "C-01"},
            "division": {"name": "Division 1", "code": "D-01"},
            "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
            "substation": {"name": "Substation 1", "code": "SS-01"},
            "feeder": {"name": "Feeder 1", "code": "F-001"},
            "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"},
        },
        "geo": {"lat": 26.9, "lng": 75.8},
    },
    {
        # Same DT as above, but missing `circle` and `feeder` — the exact
        # shape of real-world gaps found in the portal's data (empty
        # string, not an absent key).
        "meterId": "J100001",
        "serialNo": "GE84132",
        "make": "L&T",
        "phaseType": "three",
        "installStatus": "Faulty",
        "installType": "CT Operated",
        "build": "v2",
        "dtCode": "DT-001",
        "hierarchy": {
            "zone": {"name": "Jaipur Zone 1", "code": "Z-01"},
            "circle": {"name": "", "code": ""},
            "division": {"name": "Division 1", "code": "D-01"},
            "subdivision": {"name": "Subdivision 1", "code": "SD-01"},
            "substation": {"name": "Substation 1", "code": "SS-01"},
            "feeder": {"name": "", "code": ""},
            "dt": {"name": "Malviya Nagar DT 1", "code": "DT-001"},
        },
        "geo": {"lat": 26.91, "lng": 75.81},
    },
    {
        "meterId": "J100002",
        "serialNo": "AL28136",
        "make": "Genus",
        "phaseType": "single",
        "installStatus": "Decommissioned",
        "installType": "Whole Current",
        "build": "legacy",
        "dtCode": "DT-002",
        "hierarchy": {
            "zone": {"name": "Jaipur Zone 2", "code": "Z-02"},
            "circle": {"name": "Circle 2", "code": "C-02"},
            "division": {"name": "Division 2", "code": "D-02"},
            "subdivision": {"name": "Subdivision 2", "code": "SD-02"},
            "substation": {"name": "Substation 2", "code": "SS-02"},
            "feeder": {"name": "Feeder 2", "code": "F-002"},
            "dt": {"name": "Mansarovar DT 2", "code": "DT-002"},
        },
        "geo": None,
    },
]


@pytest.fixture
def fake_meters():
    return FAKE_METERS
