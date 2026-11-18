"""Integer traffic allocation, independent of the database and the external API."""

from collections.abc import Iterable
from dataclasses import dataclass, replace


class EditorError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Allocation:
    offer_id: int  # Keitaro ID, used for stable rounding across imports and DB instances.
    share: int
    pinned: bool = False
    removed: bool = False


def validate_allocations(rows: Iterable[Allocation], *, require_total: bool = True) -> None:
    rows = tuple(rows)
    ids = [row.offer_id for row in rows]
    if len(set(ids)) != len(ids):
        raise EditorError("duplicate_offer")
    for row in rows:
        if type(row.offer_id) is not int or row.offer_id <= 0:
            raise EditorError("invalid_offer_id")
        if type(row.share) is not int or not 0 <= row.share <= 100:
            raise EditorError("invalid_share")
        if row.removed and (row.share != 0 or row.pinned):
            raise EditorError("invalid_archived_offer")
    active = [row for row in rows if not row.removed]
    if sum(row.share for row in active if row.pinned) > 100:
        raise EditorError("pinned_total_exceeds_100")
    if require_total and active and sum(row.share for row in active) != 100:
        raise EditorError("total_must_equal_100")


def redistribute(rows: Iterable[Allocation]) -> tuple[Allocation, ...]:
    rows = tuple(sorted(rows, key=lambda row: row.offer_id))
    validate_allocations(rows, require_total=False)
    active = [row for row in rows if not row.removed]
    if not active:
        return rows
    available = [row for row in active if not row.pinned]
    remaining = 100 - sum(row.share for row in active if row.pinned)
    if not available:
        if remaining:
            raise EditorError("all_shares_pinned_without_100_total")
        return rows
    quotient, remainder = divmod(remaining, len(available))
    shares = {row.offer_id: quotient + (index < remainder) for index, row in enumerate(available)}
    result = tuple(
        replace(row, share=int(shares[row.offer_id])) if row.offer_id in shares else row
        for row in rows
    )
    validate_allocations(result)
    return result
