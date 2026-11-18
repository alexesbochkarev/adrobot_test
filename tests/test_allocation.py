from itertools import permutations

import pytest

from adrobot.allocation import Allocation, EditorError, redistribute


def test_rounding_is_stable_regardless_of_input_order():
    rows = [Allocation(30, 0), Allocation(10, 0), Allocation(20, 0)]
    expected = (Allocation(10, 34), Allocation(20, 33), Allocation(30, 33))
    for ordering in permutations(rows):
        assert redistribute(ordering) == expected
    assert rows == [Allocation(30, 0), Allocation(10, 0), Allocation(20, 0)]


def test_pin_and_archive_are_excluded_from_remaining_distribution():
    assert redistribute(
        [
            Allocation(10, 25, pinned=True),
            Allocation(20, 0),
            Allocation(30, 0),
            Allocation(40, 0, removed=True),
        ]
    ) == (
        Allocation(10, 25, pinned=True),
        Allocation(20, 38),
        Allocation(30, 37),
        Allocation(40, 0, removed=True),
    )


def test_allocation_invariants_over_many_sizes_and_pinned_shares():
    for count in range(1, 121):
        for pinned_share in (0, 1, 25, 50, 99, 100):
            rows = [Allocation(1, pinned_share, pinned=True)]
            rows.extend(Allocation(i + 2, 0) for i in range(count))
            result = redistribute(rows)
            assert result[0].share == pinned_share
            assert sum(row.share for row in result) == 100
            unpinned = [row.share for row in result if not row.pinned]
            assert max(unpinned) - min(unpinned) <= 1
            assert all(type(row.share) is int and 0 <= row.share <= 100 for row in result)
            assert redistribute(result) == result


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        ([Allocation(1, 0), Allocation(1, 0)], "duplicate_offer"),
        ([Allocation(0, 100)], "invalid_offer_id"),
        ([Allocation(1, -1)], "invalid_share"),
        ([Allocation(1, 101)], "invalid_share"),
        ([Allocation(1, 50.5)], "invalid_share"),
        ([Allocation(1, True)], "invalid_share"),
        ([Allocation(1, 1, removed=True)], "invalid_archived_offer"),
        ([Allocation(1, 0, pinned=True, removed=True)], "invalid_archived_offer"),
        (
            [Allocation(1, 60, pinned=True), Allocation(2, 50, pinned=True)],
            "pinned_total_exceeds_100",
        ),
        ([Allocation(1, 25, pinned=True)], "all_shares_pinned_without_100_total"),
    ],
)
def test_invalid_allocations_are_rejected(rows, code):
    with pytest.raises(EditorError) as caught:
        redistribute(rows)
    assert caught.value.code == code


def test_empty_archive_and_fully_pinned_states():
    assert redistribute([]) == ()
    assert redistribute([Allocation(1, 0, removed=True)]) == (Allocation(1, 0, removed=True),)
    rows = (Allocation(1, 25, pinned=True), Allocation(2, 75, pinned=True))
    assert redistribute(rows) == rows
