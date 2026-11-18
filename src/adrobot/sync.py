"""Fetch/Push orchestration. Campaign guards protect local edits across HTTP calls."""

from copy import deepcopy

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from adrobot.allocation import Allocation, EditorError, validate_allocations
from adrobot.editor import acknowledge_publication, publication_offers
from adrobot.editor_schemas import CampaignStreamsView, StreamOfferView, StreamView
from adrobot.keitaro import KeitaroClient, KeitaroError
from adrobot.models import Campaign, Offer, Publication, Stream, StreamOffer


class SyncError(Exception):
    def __init__(self, code: str, status: int = 409, **details):
        self.code = code
        self.status = status
        self.details = details
        super().__init__(code)


def stream_view(stream: Stream) -> StreamView:
    return StreamView(
        id=stream.id,
        keitaro_id=stream.keitaro_id,
        name=stream.name,
        position=stream.position,
        schema_kind=stream.schema_kind,
        revision=stream.revision,
        remote_present=stream.remote_present,
        is_dirty=stream.is_dirty,
        offers=[
            StreamOfferView(
                offer_id=row.offer.keitaro_id,
                name=row.offer.name,
                share=row.share,
                pinned=row.pinned,
                removed=row.removed,
                is_new=row.published_share is None,
            )
            for row in sorted(stream.offers, key=lambda x: x.offer.keitaro_id)
        ],
    )


def stream_query():
    return select(Stream).options(
        selectinload(Stream.offers).selectinload(StreamOffer.offer), selectinload(Stream.campaign)
    )


def load_stream(session: Session, remote_id: int) -> Stream:
    stream = session.scalar(stream_query().where(Stream.keitaro_id == remote_id))
    if stream is None:
        raise SyncError("stream_not_imported", 404)
    return stream


def campaign_streams(session: Session, campaign: Campaign) -> list[Stream]:
    return list(
        session.scalars(
            stream_query()
            .where(Stream.campaign_id == campaign.id)
            .order_by(Stream.position, Stream.id)
        )
    )


def campaign_view(session: Session, campaign: Campaign) -> CampaignStreamsView:
    return CampaignStreamsView(
        campaign_id=campaign.id,
        keitaro_id=campaign.keitaro_id,
        editor_revision=campaign.editor_revision,
        sync_locked=campaign.sync_token is not None,
        streams=[stream_view(stream) for stream in campaign_streams(session, campaign)],
    )


def guard_campaign(session: Session, campaign: Campaign, *, token: str | None = None) -> None:
    """CAS obtains a DB write lock until commit; optional token persists across network calls."""
    result = session.execute(
        update(Campaign)
        .where(
            Campaign.id == campaign.id,
            Campaign.editor_revision == campaign.editor_revision,
            Campaign.sync_token.is_(None),
        )
        .values(editor_revision=Campaign.editor_revision + 1, sync_token=token)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise SyncError("campaign_busy_or_changed")
    session.refresh(campaign)


def release_campaign(session: Session, stream: Stream, operation_id: str) -> None:
    result = session.execute(
        update(Campaign)
        .where(Campaign.id == stream.campaign_id, Campaign.sync_token == operation_id)
        .values(sync_token=None, editor_revision=Campaign.editor_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise SyncError("publication_lock_lost")
    session.refresh(stream.campaign)


def editable(stream: Stream, revision: int) -> None:
    if stream.campaign.sync_token:
        raise SyncError("campaign_sync_locked")
    if not stream.remote_present:
        raise SyncError("remote_stream_missing")
    if stream.revision != revision:
        raise SyncError("stale_revision")
    if stream.schema_kind != "landings":
        raise SyncError("stream_not_editable", 422)


def _without_timestamps(value):
    if isinstance(value, dict):
        return {
            key: _without_timestamps(item)
            for key, item in value.items()
            if key not in {"updated_at", "created_at"}
        }
    if isinstance(value, list):
        return [_without_timestamps(item) for item in value]
    return value


def snapshot(data: dict, campaign_id: int) -> dict:
    """Keep protected fields for conflict detection; ignore volatile association timestamps/IDs."""
    for key in ("id", "position"):
        if type(data.get(key)) is not int or data[key] <= 0:
            raise SyncError("invalid_remote_stream", 422)
    if data.get("campaign_id") != campaign_id or not isinstance(data.get("name"), str):
        raise SyncError("invalid_remote_stream", 422)
    if data.get("schema") not in {"landings", "redirect", "action"}:
        raise SyncError("unsupported_remote_schema", 422)
    offers = []
    if data["schema"] == "landings":
        if not isinstance(data.get("offers"), list):
            raise SyncError("invalid_remote_offers", 422)
        for item in data["offers"]:
            if not isinstance(item, dict) or item.get("state") != "active":
                raise SyncError("unsupported_remote_offer_state", 422)
            offers.append(
                {"offer_id": item.get("offer_id"), "share": item.get("share"), "state": "active"}
            )
        try:
            validate_allocations(Allocation(x["offer_id"], x["share"]) for x in offers)
        except EditorError as error:
            raise SyncError("invalid_remote_allocation", 422, reason=error.code) from None
        offers.sort(key=lambda x: x["offer_id"])
    return {
        "protected": _without_timestamps({k: v for k, v in data.items() if k != "offers"}),
        "offers": offers,
    }


def fetch_campaign(session: Session, client: KeitaroClient, remote_id: int) -> CampaignStreamsView:
    campaign = session.scalar(select(Campaign).where(Campaign.keitaro_id == remote_id))
    existing = campaign_streams(session, campaign) if campaign else []
    if campaign and campaign.sync_token:
        raise SyncError("campaign_sync_locked")
    if any(stream.is_dirty for stream in existing):
        raise SyncError("unpublished_changes")
    remote_campaign = client.get_campaign(remote_id)
    if remote_campaign.get("state") == "deleted":
        raise SyncError("remote_campaign_deleted", 404)
    remote_streams = [x for x in client.get_streams(remote_id) if x.get("state") != "deleted"]
    snapshots = {x["id"]: snapshot(x, remote_id) for x in remote_streams}
    if len(snapshots) != len(remote_streams):
        raise SyncError("duplicate_remote_stream", 422)
    names = {x["id"]: x["name"] for x in client.list_items("offers")}

    # No mutations before every external response has been read and validated.
    if campaign:
        guard_campaign(session, campaign)
        campaign.name = remote_campaign["name"]
    else:
        campaign = Campaign(keitaro_id=remote_id, name=remote_campaign["name"])
        session.add(campaign)
        session.flush()
    by_id = {stream.keitaro_id: stream for stream in existing}
    offer_ids = {x["offer_id"] for item in snapshots.values() for x in item["offers"]}
    offers = {
        item.keitaro_id: item
        for item in session.scalars(select(Offer).where(Offer.keitaro_id.in_(offer_ids)))
    }
    for remote_offer_id in offer_ids:
        if remote_offer_id not in offers:
            offers[remote_offer_id] = Offer(
                keitaro_id=remote_offer_id,
                name=names.get(remote_offer_id, f"Offer {remote_offer_id}"),
            )
        elif remote_offer_id in names:
            offers[remote_offer_id].name = names[remote_offer_id]
    session.add_all(offers.values())

    for remote_stream_id, confirmed in snapshots.items():
        fields = confirmed["protected"]
        stream = by_id.get(remote_stream_id)
        if stream is None:
            stream = Stream(campaign=campaign, keitaro_id=remote_stream_id, revision=1, offers=[])
            session.add(stream)
        else:
            stream.revision += 1
        stream.name = fields["name"]
        stream.position = fields["position"]
        stream.schema_kind = fields["schema"]
        stream.remote_present = True
        stream.remote_snapshot = confirmed
        links = {row.offer.keitaro_id: row for row in stream.offers}
        active_ids = set()
        for item in confirmed["offers"]:
            remote_offer_id = item["offer_id"]
            active_ids.add(remote_offer_id)
            row = links.get(remote_offer_id)
            if row is None:
                row = StreamOffer(offer=offers[remote_offer_id], pinned=False)
                stream.offers.append(row)
            # A pin survives Fetch only if the remote share did not change.
            keep_pin = bool(row.pinned and not row.removed and row.share == item["share"])
            row.share = row.published_share = item["share"]
            row.pinned = row.published_pinned = keep_pin
            row.removed = row.published_removed = False
        for remote_offer_id, row in links.items():
            if remote_offer_id not in active_ids:
                _archive(row)
    for stream in existing:
        if stream.keitaro_id not in snapshots:
            stream.remote_present = False
            stream.remote_snapshot = None
            stream.revision += 1
            for row in stream.offers:
                _archive(row)
    session.commit()
    return campaign_view(session, campaign)


def _archive(row: StreamOffer) -> None:
    row.share = row.published_share = 0
    row.pinned = row.published_pinned = False
    row.removed = row.published_removed = True


def _complete(session: Session, stream: Stream, operation: Publication, confirmed: dict) -> None:
    # Release and confirm in the same transaction, so no edit can observe a half-confirmed result.
    release_campaign(session, stream, operation.id)
    acknowledge_publication(stream, expected_revision=operation.expected_revision)
    stream.remote_snapshot = confirmed
    operation.status = "succeeded"
    operation.phase = "completed"
    operation.error_code = None
    operation.result = stream_view(stream).model_dump(mode="json")
    session.commit()


def push_stream(
    session: Session, client: KeitaroClient, remote_id: int, revision: int, operation_id: str
) -> Publication:
    stream = load_stream(session, remote_id)
    existing = session.get(Publication, operation_id)
    if existing:
        if existing.stream_id != stream.id or existing.expected_revision != revision:
            raise SyncError("idempotency_key_reused")
        if existing.status == "succeeded":
            return existing
        raise SyncError("publication_requires_review", operation_id=existing.id)
    editable(stream, revision)
    if not stream.is_dirty:
        raise SyncError("no_unpublished_changes")
    if stream.remote_snapshot is None:
        raise SyncError("fetch_required")
    desired = publication_offers(stream, expected_revision=revision)
    guard_campaign(session, stream.campaign, token=operation_id)
    operation = Publication(
        id=operation_id,
        stream_id=stream.id,
        expected_revision=revision,
        before_snapshot=deepcopy(stream.remote_snapshot),
        desired_offers=desired,
    )
    session.add(operation)
    session.commit()
    written = False
    try:
        current = snapshot(client.get_stream(remote_id), stream.campaign.keitaro_id)
        if current != operation.before_snapshot:
            raise SyncError("remote_stream_changed")
        for item in desired:
            offer = client.get_offer(item["offer_id"])
            if offer.get("state") != "active":
                raise SyncError("offer_unavailable", 422, offer_id=item["offer_id"])
        operation.phase = "updating"
        session.commit()
        client.update_stream_offers(remote_id, desired)
        written = True
        operation.phase = "verifying"
        session.commit()
        confirmed = snapshot(client.get_stream(remote_id), stream.campaign.keitaro_id)
        if confirmed != {**operation.before_snapshot, "offers": desired}:
            raise SyncError("publication_verification_failed")
        _complete(session, stream, operation, confirmed)
        return operation
    except (KeitaroError, SyncError) as error:
        uncertain = written or (isinstance(error, KeitaroError) and error.uncertain)
        operation.status = (
            "unknown"
            if uncertain
            else ("conflict" if isinstance(error, SyncError) and error.status == 409 else "failed")
        )
        operation.error_code = error.code
        if not uncertain:
            release_campaign(session, stream, operation.id)
        session.commit()
        raise SyncError(
            error.code,
            502 if uncertain or isinstance(error, KeitaroError) else error.status,
            operation_id=operation.id,
            publication_status=operation.status,
        ) from None


def reconcile_publication(
    session: Session, client: KeitaroClient, operation_id: str
) -> Publication:
    operation = session.get(Publication, operation_id)
    if operation is None:
        raise SyncError("publication_not_found", 404)
    if operation.status == "succeeded":
        return operation
    if operation.status != "unknown" and not (
        operation.status == "pending" and operation.phase == "verifying"
    ):
        raise SyncError("publication_not_reconcilable")
    stream = session.scalar(stream_query().where(Stream.id == operation.stream_id))
    if stream.campaign.sync_token != operation.id:
        raise SyncError("publication_lock_lost")
    confirmed = snapshot(client.get_stream(stream.keitaro_id), stream.campaign.keitaro_id)
    if confirmed != {**operation.before_snapshot, "offers": operation.desired_offers}:
        raise SyncError("publication_not_confirmed", operation_id=operation.id)
    _complete(session, stream, operation, confirmed)
    return operation
