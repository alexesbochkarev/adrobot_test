"""Local editor operations. The caller owns the transaction and commits/rolls back.

No network calls occur here. Only acknowledge_publication can advance the confirmed
snapshot; the integration layer must call it AFTER confirming the external write.
"""

from collections.abc import Iterable
from dataclasses import replace

from adrobot.allocation import Allocation, EditorError, redistribute, validate_allocations
from adrobot.models import Campaign, Offer, Stream, StreamOffer


def allocations(stream: Stream) -> tuple[Allocation, ...]:
    return tuple(
        sorted(
            (
                Allocation(row.offer.keitaro_id, row.share, row.pinned, row.removed)
                for row in stream.offers
            ),
            key=lambda row: row.offer_id,
        )
    )


def new_imported_stream(
    *,
    campaign: Campaign,
    keitaro_id: int,
    name: str,
    position: int,
    schema_kind: str,
    offers: Iterable[tuple[Offer, int]] = (),
) -> Stream:
    """Build a first-import snapshot. Re-fetch/merge belongs to the integration layer."""
    entries = tuple(offers)
    if schema_kind not in {"landings", "redirect", "action"}:
        raise EditorError("unsupported_stream_schema")
    if entries and schema_kind != "landings":
        raise EditorError("stream_not_editable")
    validate_allocations(Allocation(offer.keitaro_id, share) for offer, share in entries)
    return Stream(
        campaign=campaign,
        keitaro_id=keitaro_id,
        name=name,
        position=position,
        schema_kind=schema_kind,
        revision=1,
        offers=[
            StreamOffer(
                offer=offer,
                share=share,
                pinned=False,
                removed=False,
                published_share=share,
                published_pinned=False,
                published_removed=False,
            )
            for offer, share in entries
        ],
    )


def _check(stream: Stream, expected_revision: int) -> None:
    if stream.revision != expected_revision:
        raise EditorError("stale_revision")
    if stream.schema_kind != "landings":
        raise EditorError("stream_not_editable")


def _find(rows: tuple[Allocation, ...], offer_id: int) -> Allocation:
    for row in rows:
        if row.offer_id == offer_id:
            return row
    raise EditorError("offer_not_in_stream")


def _apply(
    stream: Stream, rows: tuple[Allocation, ...], *, added_offer: Offer | None = None
) -> None:
    # Plan and validate before touching ORM objects, so rejected operations leave no partial draft.
    validate_allocations(rows)
    if rows == allocations(stream):
        return
    by_id = {row.offer.keitaro_id: row for row in stream.offers}
    wanted_ids = {row.offer_id for row in rows}
    missing_ids = wanted_ids - by_id.keys()
    if missing_ids and (added_offer is None or missing_ids != {added_offer.keitaro_id}):
        raise RuntimeError("Missing offer for the new association")
    for row in list(stream.offers):
        if row.offer.keitaro_id not in wanted_ids:
            stream.offers.remove(row)
    for value in rows:
        row = by_id.get(value.offer_id)
        if row is None:
            row = StreamOffer(
                offer=added_offer,
                published_share=None,
                published_pinned=False,
                published_removed=False,
            )
            stream.offers.append(row)
        row.share = value.share
        row.pinned = value.pinned
        row.removed = value.removed
    stream.revision += 1


def add_offer(stream: Stream, offer: Offer, *, expected_revision: int) -> None:
    _check(stream, expected_revision)
    rows = allocations(stream)
    existing = next((row for row in rows if row.offer_id == offer.keitaro_id), None)
    if existing is not None:
        if not existing.removed:
            raise EditorError("offer_already_active")
        restore_offer(stream, offer.keitaro_id, expected_revision=expected_revision)
        return
    plan = redistribute((*rows, Allocation(offer.keitaro_id, 0)))
    _apply(stream, plan, added_offer=offer)


def remove_offer(stream: Stream, offer_id: int, *, expected_revision: int) -> None:
    _check(stream, expected_revision)
    rows = allocations(stream)
    target = _find(rows, offer_id)
    if target.removed:
        return
    if sum(not row.removed for row in rows) == 1:
        raise EditorError("cannot_remove_last_active_offer")
    association = next(row for row in stream.offers if row.offer.keitaro_id == offer_id)
    if association.published_share is None:
        # A never-published association does not belong in the archive.
        plan = tuple(row for row in rows if row.offer_id != offer_id)
    else:
        plan = tuple(
            replace(row, share=0, pinned=False, removed=True) if row == target else row
            for row in rows
        )
    _apply(stream, redistribute(plan))


def restore_offer(stream: Stream, offer_id: int, *, expected_revision: int) -> None:
    _check(stream, expected_revision)
    rows = allocations(stream)
    target = _find(rows, offer_id)
    if not target.removed:
        return
    plan = tuple(replace(row, removed=False) if row == target else row for row in rows)
    _apply(stream, redistribute(plan))


def pin_offer(
    stream: Stream, offer_id: int, *, expected_revision: int, share: int | None = None
) -> None:
    _check(stream, expected_revision)
    rows = allocations(stream)
    target = _find(rows, offer_id)
    if target.removed:
        raise EditorError("cannot_pin_archived_offer")
    pinned = replace(target, pinned=True, share=target.share if share is None else share)
    if pinned == target:
        return
    plan = tuple(pinned if row == target else row for row in rows)
    _apply(stream, redistribute(plan))


def unpin_offer(stream: Stream, offer_id: int, *, expected_revision: int) -> None:
    _check(stream, expected_revision)
    rows = allocations(stream)
    target = _find(rows, offer_id)
    if not target.pinned:
        return
    plan = tuple(replace(row, pinned=False) if row == target else row for row in rows)
    _apply(stream, redistribute(plan))


def cancel(stream: Stream, *, expected_revision: int) -> None:
    _check(stream, expected_revision)
    snapshot = tuple(
        sorted(
            (
                Allocation(
                    row.offer.keitaro_id,
                    row.published_share,
                    row.published_pinned,
                    row.published_removed,
                )
                for row in stream.offers
                if row.published_share is not None
            ),
            key=lambda row: row.offer_id,
        )
    )
    # Do not redistribute: Cancel must restore the exact confirmed weights and pins.
    _apply(stream, snapshot)


def publication_offers(stream: Stream, *, expected_revision: int) -> list[dict]:
    """Only the offer array for a future API update; never changes the confirmed state."""
    _check(stream, expected_revision)
    rows = allocations(stream)
    validate_allocations(rows)
    return [
        {"offer_id": row.offer_id, "share": row.share, "state": "active"}
        for row in rows
        if not row.removed
    ]


def acknowledge_publication(stream: Stream, *, expected_revision: int) -> None:
    """Call only for the exact revision successfully published and verified in Keitaro."""
    _check(stream, expected_revision)
    validate_allocations(allocations(stream))
    if not stream.is_dirty:
        return
    for row in stream.offers:
        row.published_share = row.share
        row.published_pinned = row.pinned
        row.published_removed = row.removed
    stream.revision += 1
