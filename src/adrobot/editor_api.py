from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Path, Request
from sqlalchemy import select

from adrobot import editor
from adrobot.campaigns import Db, Keitaro
from adrobot.editor_schemas import (
    AddOfferRequest,
    CampaignStreamsView,
    EditRequest,
    PinRequest,
    PublicationView,
    StreamView,
)
from adrobot.keitaro import get_keitaro
from adrobot.models import Campaign, Offer, Publication
from adrobot.schemas import ReferenceItem
from adrobot.sync import (
    SyncError,
    campaign_view,
    editable,
    fetch_campaign,
    guard_campaign,
    load_stream,
    push_stream,
    reconcile_publication,
    stream_view,
)

router = APIRouter(tags=["editor"])
RemoteId = Annotated[int, Path(gt=0)]


@router.get("/campaigns", response_model=list[ReferenceItem])
def list_campaigns(client: Keitaro) -> list[dict]:
    return [item for item in client.list_items("campaigns") if item.get("state") != "deleted"]


@router.post("/campaigns/{campaign_id}/fetch", response_model=CampaignStreamsView)
def fetch(campaign_id: RemoteId, session: Db, client: Keitaro) -> CampaignStreamsView:
    return fetch_campaign(session, client, campaign_id)


@router.get("/campaigns/{campaign_id}/streams", response_model=CampaignStreamsView)
def cached_streams(campaign_id: RemoteId, session: Db) -> CampaignStreamsView:
    campaign = session.scalar(select(Campaign).where(Campaign.keitaro_id == campaign_id))
    if campaign is None:
        raise SyncError("campaign_not_imported", 404)
    return campaign_view(session, campaign)


@router.post("/streams/{stream_id}/offers", response_model=StreamView)
def add(stream_id: RemoteId, body: AddOfferRequest, session: Db, client: Keitaro) -> StreamView:
    stream = load_stream(session, stream_id)
    editable(stream, body.expected_revision)
    data = client.get_offer(body.offer_id)
    if data.get("state") != "active" or not isinstance(data.get("name"), str):
        raise SyncError("offer_unavailable", 422)
    guard_campaign(session, stream.campaign)
    offer = session.scalar(select(Offer).where(Offer.keitaro_id == body.offer_id))
    if offer is None:
        offer = Offer(keitaro_id=body.offer_id, name=data["name"])
    editor.add_offer(stream, offer, expected_revision=body.expected_revision)
    session.commit()
    return stream_view(stream)


@router.post("/streams/{stream_id}/offers/{offer_id}/{action}", response_model=StreamView)
def edit_offer(
    stream_id: RemoteId,
    offer_id: RemoteId,
    action: Literal["remove", "restore", "pin", "unpin"],
    body: PinRequest,
    session: Db,
    request: Request,
) -> StreamView:
    if action != "pin" and body.share is not None:
        raise SyncError("share_only_allowed_for_pin", 422)
    stream = load_stream(session, stream_id)
    editable(stream, body.expected_revision)
    if action == "restore":
        data = get_keitaro(request).get_offer(offer_id)
        if data.get("state") != "active":
            raise SyncError("offer_unavailable", 422)
    guard_campaign(session, stream.campaign)
    operations = {
        "remove": editor.remove_offer,
        "restore": editor.restore_offer,
        "unpin": editor.unpin_offer,
    }
    if action == "pin":
        editor.pin_offer(
            stream, offer_id, expected_revision=body.expected_revision, share=body.share
        )
    else:
        operations[action](stream, offer_id, expected_revision=body.expected_revision)
    session.commit()
    return stream_view(stream)


@router.post("/streams/{stream_id}/cancel", response_model=StreamView)
def cancel(stream_id: RemoteId, body: EditRequest, session: Db) -> StreamView:
    stream = load_stream(session, stream_id)
    editable(stream, body.expected_revision)
    guard_campaign(session, stream.campaign)
    editor.cancel(stream, expected_revision=body.expected_revision)
    session.commit()
    return stream_view(stream)


@router.post("/streams/{stream_id}/push", response_model=PublicationView)
def push(
    stream_id: RemoteId,
    body: EditRequest,
    session: Db,
    client: Keitaro,
    idempotency_key: Annotated[UUID, Header()],
) -> Publication:
    return push_stream(session, client, stream_id, body.expected_revision, str(idempotency_key))


@router.get("/publications/{operation_id}", response_model=PublicationView)
def publication(operation_id: UUID, session: Db) -> Publication:
    result = session.get(Publication, str(operation_id))
    if result is None:
        raise SyncError("publication_not_found", 404)
    return result


@router.post("/publications/{operation_id}/reconcile", response_model=PublicationView)
def reconcile(operation_id: UUID, session: Db, client: Keitaro) -> Publication:
    return reconcile_publication(session, client, str(operation_id))
