from app.index import MeterIndex, build_hierarchy_tree, to_summary


def test_normalize_marks_incomplete_hierarchy(fake_meters):
    index = MeterIndex(fake_meters)

    complete = index.get("J100000")
    incomplete = index.get("J100001")

    assert complete.hierarchy_complete is True
    assert incomplete.hierarchy_complete is False
    # Empty-string fields from the portal must become None, not "".
    assert incomplete.hierarchy.circle is None
    assert incomplete.hierarchy.feeder is None
    assert incomplete.hierarchy.zone.code == "Z-01"


def test_search_filters_combine(fake_meters):
    index = MeterIndex(fake_meters)

    results, total = index.search(install_status="Faulty", phase_type="three")
    assert total == 1
    assert results[0].meter_id == "J100001"

    results, total = index.search(dt_code="DT-001")
    assert total == 2

    results, total = index.search(q="al281")
    assert total == 1
    assert results[0].meter_id == "J100002"


def test_search_pagination(fake_meters):
    index = MeterIndex(fake_meters)
    page1, total = index.search(page=1, page_size=2)
    page2, _ = index.search(page=2, page_size=2)
    assert total == 3
    assert len(page1) == 2
    assert len(page2) == 1


def test_nearby_orders_by_distance_and_skips_missing_geo(fake_meters):
    index = MeterIndex(fake_meters)
    results = index.nearby(lat=26.9, lng=75.8, radius_km=None, limit=10)
    # J100002 has no geo and must be excluded, not error out.
    assert {r.meter.meter_id for r in results} == {"J100000", "J100001"}
    assert results[0].meter.meter_id == "J100000"
    assert results[0].distance_km <= results[1].distance_km


def test_to_summary_drops_detail_fields(fake_meters):
    index = MeterIndex(fake_meters)
    summary = to_summary(index.get("J100000"))
    assert summary.meter_id == "J100000"
    assert not hasattr(summary, "hierarchy")


def test_hierarchy_tree_flags_missing_levels_as_data_quality_issue(fake_meters):
    index = MeterIndex(fake_meters)
    tree = build_hierarchy_tree(index)

    assert tree.total_meters == 3
    # DT-001 has one meter missing circle+feeder -> two issues recorded.
    dt001_issues = [i for i in tree.data_quality_issues if i.dt_code == "DT-001"]
    assert len(dt001_issues) == 2
    levels_flagged = {i.description.split(":")[0] for i in dt001_issues}
    assert levels_flagged == {"circle", "feeder"}

    # Despite the gap, DT-001 must still be resolved into the tree using
    # the majority (non-missing) value at each level.
    zone1 = next(z for z in tree.zones if z.code == "Z-01")
    assert zone1.meter_count == 2
    # walk down to the DT leaf and check it exists with the right count
    def find(node, level, code):
        if node.level == level and node.code == code:
            return node
        for child in node.children:
            found = find(child, level, code)
            if found:
                return found
        return None

    dt_node = find(zone1, "dt", "DT-001")
    assert dt_node is not None
    assert dt_node.meter_count == 2
