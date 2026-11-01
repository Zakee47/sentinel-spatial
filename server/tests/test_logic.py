from server.logic import funnel, heatmap


def test_heatmap_sums_look_duration_and_builds_gaze_points():
    result = heatmap(
        [
            {
                "type": "look",
                "zone_id": "shelf-a",
                "payload": {"duration_s": 2, "gaze_hit_xyz": [1, 2, 3]},
            },
            {
                "type": "look",
                "zone_id": "shelf-a",
                "x": 4,
                "y": 5,
                "z": 6,
                "payload": {"duration_s": 3},
            },
            {
                "type": "interest",
                "zone_id": "shelf-a",
                "x": 7,
                "y": 8,
                "payload": {"duration_s": 9},
            },
            {
                "type": "pass_by",
                "zone_id": "shelf-a",
                "x": 10,
                "y": 11,
                "payload": {"duration_s": 20},
            },
        ]
    )

    assert result["zones"] == {"shelf-a": {"look_s": 5.0, "looks": 2}}
    assert result["points"] == [
        [1.0, 2.0, 3.0, 2.0],
        [4.0, 5.0, 6.0, 3.0],
        [7.0, 8.0, 0.0, 9.0],
    ]


def test_funnel_scopes_product_events_and_applies_flag_rule():
    products = [
        {"product_id": "A", "name": "Alpha", "zone_id": "shelf-a"},
        {"product_id": "B", "name": "Beta", "zone_id": "shelf-a"},
        {"product_id": "C", "name": "Gamma", "zone_id": "shelf-b"},
        {"product_id": "D", "name": "Delta", "zone_id": "shelf-b"},
    ]
    events = [
        {"type": "look", "zone_id": "shelf-a", "product_id": "A"},
        {"type": "interest", "zone_id": "shelf-a", "product_id": "A"},
        {"type": "pick_up", "zone_id": "shelf-a", "product_id": "A"},
        {"type": "put_back", "zone_id": "shelf-a", "product_id": "A"},
        {"type": "look", "zone_id": "shelf-a"},
        {"type": "pick_up", "zone_id": "shelf-a"},
        {"type": "put_back", "zone_id": "shelf-b", "product_id": "C"},
        {"type": "kept", "zone_id": "shelf-b", "product_id": "D"},
    ]

    rows = funnel(products, events, {})
    by_id = {row["product_id"]: row for row in rows}

    assert (by_id["A"]["looked"], by_id["A"]["interested"]) == (2, 1)
    assert (by_id["B"]["looked"], by_id["B"]["interested"]) == (1, 0)
    assert (by_id["A"]["picked_up"], by_id["A"]["put_back"]) == (2, 1)
    assert by_id["A"]["put_back_rate"] == 0.5
    assert by_id["B"]["put_back_rate"] == 0.0
    assert by_id["C"]["put_back"] == 1
    assert by_id["D"]["kept"] == 1


def test_funnel_flags_only_the_high_look_low_conversion_product():
    products = [
        {"product_id": str(i), "name": f"Product {i}", "zone_id": f"zone-{i}"}
        for i in range(4)
    ]
    events = [
        *({"type": "look", "zone_id": "zone-0", "product_id": "0"} for _ in range(12)),
        *({"type": "look", "zone_id": "zone-1", "product_id": "1"} for _ in range(6)),
        *({"type": "look", "zone_id": "zone-2", "product_id": "2"} for _ in range(3)),
        {"type": "look", "zone_id": "zone-3", "product_id": "3"},
    ]

    rows = funnel(products, events, {"1": 10, "2": 20, "3": 30})

    assert [
        row["product_id"] for row in rows if row["flag_high_attention_low_conversion"]
    ] == ["0"]


def test_funnel_does_not_flag_products_without_looks():
    products = [
        {"product_id": str(i), "name": f"Product {i}", "zone_id": f"zone-{i}"}
        for i in range(4)
    ]

    rows = funnel(products, [], {})

    assert all(not row["flag_high_attention_low_conversion"] for row in rows)
