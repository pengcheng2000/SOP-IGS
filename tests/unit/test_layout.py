from app.services.layout import LayoutPhoto, plan_layout, row_partitions


def test_row_partitions_are_generated_instead_of_count_rules():
    partitions = row_partitions(4)
    assert (2, 2) in partitions
    assert (1, 1, 2) in partitions
    assert all(sum(candidate) == 4 for candidate in partitions)


def test_layout_is_deterministic_and_preserves_capacity():
    photos = [LayoutPhoto(str(index), 1600 if index % 2 else 900, 900 if index % 2 else 1600) for index in range(20)]
    first = plan_layout(photos)
    second = plan_layout(photos)
    assert first == second
    assert sum(sum(page.rows) for page in first.pages) == 20
    assert len(first.pages) <= 4
    assert all(max(page.rows) <= 3 and len(page.rows) <= 3 for page in first.pages)


def test_common_four_photo_case_prefers_balanced_grid():
    photos = [LayoutPhoto(str(index), 1600, 900) for index in range(4)]
    plan = plan_layout(photos)
    assert len(plan.pages) == 1
    assert plan.pages[0].rows == (2, 2)


def test_maximum_project_photo_count_is_planned_without_reordering():
    photos = [
        LayoutPhoto(str(index), 1200 + index % 4 * 200, 900 + index % 3 * 250)
        for index in range(200)
    ]
    plan = plan_layout(photos)
    assert sum(sum(page.rows) for page in plan.pages) == 200
    assert len(plan.pages) <= 34
