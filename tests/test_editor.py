import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.exc import StaleDataError

from adrobot.allocation import Allocation, EditorError
from adrobot.db import create_db_engine
from adrobot.editor import (
    acknowledge_publication,
    add_offer,
    allocations,
    cancel,
    new_imported_stream,
    pin_offer,
    publication_offers,
    remove_offer,
    restore_offer,
    unpin_offer,
)
from adrobot.models import Campaign, Offer, Stream, StreamOffer


@pytest.fixture
def editor(migrated_database):
    engine = create_db_engine(migrated_database)
    with Session(engine, expire_on_commit=False) as session:
        campaign = Campaign(keitaro_id=100, name="Test")
        offers = [Offer(keitaro_id=i, name=f"Offer {i}") for i in (10, 20, 30, 40, 50)]
        stream = new_imported_stream(
            campaign=campaign,
            keitaro_id=200,
            name="Offers",
            position=2,
            schema_kind="landings",
            offers=zip(offers[:3], (50, 30, 20), strict=True),
        )
        session.add_all([stream, *offers])
        session.commit()
        yield session, stream, offers
    engine.dispose()


def test_import_preserves_exact_weights_and_is_clean(editor):
    _session, stream, _offers = editor
    assert allocations(stream) == (Allocation(10, 50), Allocation(20, 30), Allocation(30, 20))
    assert not stream.is_dirty
    assert stream.revision == 1


def test_add_draft_survives_session_and_cancel_restores_original(editor):
    session, stream, offers = editor
    original = allocations(stream)
    add_offer(stream, offers[3], expected_revision=1)
    assert stream.is_dirty
    assert [row.share for row in allocations(stream)] == [25, 25, 25, 25]
    assert stream.revision == 2
    session.commit()
    with Session(session.bind) as reopened:
        loaded = reopened.get(Stream, stream.id)
        assert loaded.is_dirty
        cancel(loaded, expected_revision=2)
        assert allocations(loaded) == original
        assert not loaded.is_dirty
        reopened.commit()
    session.expire_all()
    assert not stream.is_dirty
    assert len(stream.offers) == 3
    assert session.get(Offer, offers[3].id) is not None
    assert session.scalar(select(func.count()).select_from(StreamOffer)) == 3


def test_remove_publish_restore_and_cancel_archive(editor):
    session, stream, _offers = editor
    remove_offer(stream, 20, expected_revision=1)
    assert allocations(stream) == (
        Allocation(10, 50),
        Allocation(20, 0, removed=True),
        Allocation(30, 50),
    )
    payload = publication_offers(stream, expected_revision=2)
    assert payload == [
        {"offer_id": 10, "share": 50, "state": "active"},
        {"offer_id": 30, "share": 50, "state": "active"},
    ]
    assert stream.is_dirty  # Preparing the payload does not acknowledge an external write.
    acknowledge_publication(stream, expected_revision=2)
    assert not stream.is_dirty
    session.commit()
    session.expire_all()
    assert len(stream.offers) == 3
    archived = allocations(stream)
    restore_offer(stream, 20, expected_revision=3)
    assert [row.share for row in allocations(stream)] == [34, 33, 33]
    cancel(stream, expected_revision=4)
    assert allocations(stream) == archived
    assert not stream.is_dirty


def test_pinning_example_from_video(editor):
    session, stream, offers = editor
    add_offer(stream, offers[3], expected_revision=1)
    acknowledge_publication(stream, expected_revision=2)
    pin_offer(stream, 10, expected_revision=3)  # Pin the current 25%.
    remove_offer(stream, 40, expected_revision=4)
    assert allocations(stream) == (
        Allocation(10, 25, pinned=True),
        Allocation(20, 38),
        Allocation(30, 37),
        Allocation(40, 0, removed=True),
    )
    acknowledge_publication(stream, expected_revision=5)
    session.commit()
    restore_offer(stream, 40, expected_revision=6)
    assert [row.share for row in allocations(stream)] == [25, 25, 25, 25]
    assert allocations(stream)[0].pinned


def test_cancel_restores_pinned_removed_offer(editor):
    _session, stream, _offers = editor
    pin_offer(stream, 10, expected_revision=1, share=25)
    acknowledge_publication(stream, expected_revision=2)
    snapshot = allocations(stream)
    remove_offer(stream, 10, expected_revision=3)
    assert allocations(stream)[0] == Allocation(10, 0, removed=True)
    cancel(stream, expected_revision=4)
    assert allocations(stream) == snapshot
    assert not stream.is_dirty


def test_restore_clears_old_pin_but_cancel_preserves_confirmed_snapshot(editor):
    _session, stream, _offers = editor
    pin_offer(stream, 10, expected_revision=1, share=25)
    remove_offer(stream, 10, expected_revision=2)
    acknowledge_publication(stream, expected_revision=3)
    restore_offer(stream, 10, expected_revision=4)
    assert not allocations(stream)[0].pinned
    assert [row.share for row in allocations(stream)] == [34, 33, 33]


def test_add_archived_offer_restores_existing_association(editor):
    session, stream, offers = editor
    remove_offer(stream, 20, expected_revision=1)
    acknowledge_publication(stream, expected_revision=2)
    add_offer(stream, offers[1], expected_revision=3)
    session.commit()
    assert len(stream.offers) == 3
    assert all(not row.removed for row in allocations(stream))


def test_remove_never_published_association_does_not_archive_it(editor):
    session, stream, offers = editor
    add_offer(stream, offers[3], expected_revision=1)
    remove_offer(stream, 40, expected_revision=2)
    session.commit()
    assert len(stream.offers) == 3
    assert session.get(Offer, offers[3].id) is not None
    # Redistribution differs from the original 50/30/20; Cancel still restores that snapshot.
    assert stream.is_dirty
    cancel(stream, expected_revision=3)
    assert [row.share for row in allocations(stream)] == [50, 30, 20]


def test_unpin_redistributes_and_cancel_restores_pin(editor):
    _session, stream, _offers = editor
    pin_offer(stream, 10, expected_revision=1, share=25)
    acknowledge_publication(stream, expected_revision=2)
    unpin_offer(stream, 10, expected_revision=3)
    assert [row.share for row in allocations(stream)] == [34, 33, 33]
    cancel(stream, expected_revision=4)
    assert allocations(stream)[0] == Allocation(10, 25, pinned=True)


def test_rejected_operation_does_not_mutate_draft(editor):
    _session, stream, offers = editor
    pin_offer(stream, 10, expected_revision=1, share=80)
    original = allocations(stream)
    with pytest.raises(EditorError, match="pinned_total_exceeds_100"):
        pin_offer(stream, 20, expected_revision=2, share=30)
    assert allocations(stream) == original and stream.revision == 2
    with pytest.raises(EditorError, match="offer_already_active"):
        add_offer(stream, offers[0], expected_revision=2)
    assert allocations(stream) == original and stream.revision == 2
    with pytest.raises(EditorError, match="invalid_share"):
        pin_offer(stream, 20, expected_revision=2, share=1.5)
    assert allocations(stream) == original and stream.revision == 2


def test_last_offer_and_impossible_fully_pinned_allocation_are_rejected(editor):
    _session, stream, _offers = editor
    remove_offer(stream, 20, expected_revision=1)
    pin_offer(stream, 10, expected_revision=2, share=25)
    before = allocations(stream)
    with pytest.raises(EditorError, match="all_shares_pinned_without_100_total"):
        remove_offer(stream, 30, expected_revision=3)
    assert allocations(stream) == before and stream.revision == 3
    unpin_offer(stream, 10, expected_revision=3)
    remove_offer(stream, 30, expected_revision=4)
    with pytest.raises(EditorError, match="cannot_remove_last_active_offer"):
        remove_offer(stream, 10, expected_revision=5)


def test_stale_client_revision_cannot_edit_or_acknowledge(editor):
    _session, stream, offers = editor
    add_offer(stream, offers[3], expected_revision=1)
    for operation in (cancel, acknowledge_publication, publication_offers):
        with pytest.raises(EditorError, match="stale_revision"):
            operation(stream, expected_revision=1)
    assert stream.is_dirty and stream.revision == 2


def test_no_op_does_not_increment_revision(editor):
    _session, stream, _offers = editor
    cancel(stream, expected_revision=1)
    acknowledge_publication(stream, expected_revision=1)
    restore_offer(stream, 10, expected_revision=1)
    unpin_offer(stream, 10, expected_revision=1)
    assert stream.revision == 1
    pin_offer(stream, 10, expected_revision=1)
    pin_offer(stream, 10, expected_revision=2)
    assert stream.revision == 2


def test_unknown_offer_and_archived_pin_are_rejected(editor):
    _session, stream, _offers = editor
    with pytest.raises(EditorError, match="offer_not_in_stream"):
        remove_offer(stream, 999, expected_revision=1)
    remove_offer(stream, 10, expected_revision=1)
    with pytest.raises(EditorError, match="cannot_pin_archived_offer"):
        pin_offer(stream, 10, expected_revision=2)


def test_offer_state_is_specific_to_each_stream(editor):
    session, stream, offers = editor
    second = new_imported_stream(
        campaign=stream.campaign,
        keitaro_id=201,
        name="Other",
        position=3,
        schema_kind="landings",
        offers=[(offers[0], 100)],
    )
    session.add(second)
    session.commit()
    pin_offer(stream, 10, expected_revision=1, share=25)
    remove_offer(stream, 10, expected_revision=2)
    session.commit()
    assert allocations(second) == (Allocation(10, 100),)
    assert not second.is_dirty


def test_redirect_stream_is_stored_but_not_edited(editor):
    session, stream, offers = editor
    redirect = new_imported_stream(
        campaign=stream.campaign,
        keitaro_id=199,
        name="Geo redirect",
        position=1,
        schema_kind="redirect",
    )
    session.add(redirect)
    session.commit()
    assert not redirect.is_dirty
    with pytest.raises(EditorError, match="stream_not_editable"):
        add_offer(redirect, offers[0], expected_revision=1)
    assert redirect.offers == []


def test_empty_offer_stream_can_receive_first_offer_and_cancel(editor):
    session, stream, offers = editor
    empty = new_imported_stream(
        campaign=stream.campaign,
        keitaro_id=201,
        name="Empty",
        position=3,
        schema_kind="landings",
    )
    session.add(empty)
    session.commit()
    add_offer(empty, offers[0], expected_revision=1)
    assert allocations(empty) == (Allocation(10, 100),)
    cancel(empty, expected_revision=2)
    session.commit()
    assert not empty.is_dirty and empty.offers == []


def test_concurrent_edit_is_rejected_and_rolls_back_all_link_changes(editor):
    session, stream, _offers = editor
    with Session(session.bind) as first, Session(session.bind) as second:
        query = (
            select(Stream)
            .where(Stream.id == stream.id)
            .options(selectinload(Stream.offers).selectinload(StreamOffer.offer))
        )
        a = first.scalar(query)
        b = second.scalar(query)
        remove_offer(a, 20, expected_revision=1)
        pin_offer(b, 10, expected_revision=1, share=25)
        first.commit()
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
    session.expire_all()
    assert allocations(stream) == (
        Allocation(10, 50),
        Allocation(20, 0, removed=True),
        Allocation(30, 50),
    )
    assert stream.revision == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"share": -1},
        {"share": 101},
        {"removed": True, "share": 1},
        {"removed": True, "share": 0, "pinned": True},
        {"published_share": 101},
        {"published_share": None, "published_pinned": True},
        {"published_share": 1, "published_removed": True},
        {"offer_id": 99999},
    ],
)
def test_database_rejects_invalid_association(editor, changes):
    session, stream, offers = editor
    values = {
        "stream_id": stream.id,
        "offer_id": offers[3].id,
        "share": 0,
        "published_share": None,
        **changes,
    }
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(insert(StreamOffer).values(**values))


def test_duplicate_association_is_rejected(editor):
    session, stream, offers = editor
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            insert(StreamOffer).values(stream_id=stream.id, offer_id=offers[0].id, share=100)
        )


def test_stream_delete_cascades_links_but_keeps_offers(editor):
    session, stream, _offers = editor
    session.execute(delete(Stream).where(Stream.id == stream.id))
    session.commit()
    assert session.scalar(select(func.count()).select_from(StreamOffer)) == 0
    assert session.scalar(select(func.count()).select_from(Offer)) == 5


def test_editor_migration_preserves_existing_campaigns(database_url):
    config = Config("alembic.ini")
    command.upgrade(config, "0002")
    engine = create_db_engine(database_url)
    try:
        with Session(engine) as session:
            session.add(Campaign(keitaro_id=100, name="Existing"))
            session.commit()
        command.upgrade(config, "head")
        command.check(config)
        with Session(engine) as session:
            assert session.scalar(select(Campaign.name)) == "Existing"
        command.downgrade(config, "0002")
        with Session(engine) as session:
            assert session.scalar(select(Campaign.name)) == "Existing"
    finally:
        engine.dispose()
