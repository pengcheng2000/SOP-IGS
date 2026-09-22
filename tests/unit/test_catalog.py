from app.domain.catalog import display_numbers, selected_with_ancestors, tree_payload


def test_deep_selection_keeps_ancestors_and_restarts_sibling_numbers():
    selected = ["alarm_bms", "signal_do"]
    kept = selected_with_ancestors(selected)
    assert {"communications", "alarm_protection", "alarm_bms", "signal_test", "signal_do"} <= kept
    numbers = display_numbers(selected)
    assert numbers["communications"] == "5.1"
    assert numbers["alarm_protection"] == "5.1.1"
    assert numbers["alarm_bms"] == "5.1.1.1"
    assert numbers["signal_test"] == "5.2"
    assert numbers["signal_do"] == "5.2.1"


def test_tree_state_is_indeterminate_for_partial_group_selection():
    tree = tree_payload(["cabinet_strength_lifting"])
    cabinet = next(item for item in tree if item["id"] == "cabinet_strength")
    assert cabinet["state"] == "indeterminate"
    lifting = next(item for item in cabinet["children"] if item["id"] == "cabinet_strength_lifting")
    assert lifting["state"] == "checked"

