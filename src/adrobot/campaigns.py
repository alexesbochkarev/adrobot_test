from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from adrobot.config import Settings
from adrobot.db import get_session
from adrobot.keitaro import KeitaroClient, KeitaroError, get_keitaro
from adrobot.models import Campaign, CampaignCreation
from adrobot.schemas import CampaignCreate, CampaignCreated, CreationStatus, ReferenceItem

router = APIRouter()
Db = Annotated[Session, Depends(get_session)]
Keitaro = Annotated[KeitaroClient, Depends(get_keitaro)]


@router.get("/reference/domains", response_model=list[ReferenceItem], tags=["reference"])
def domains(client: Keitaro) -> list[dict]:
    return [x for x in client.list_items("domains") if x.get("state") == "active"]


@router.get("/reference/groups", response_model=list[ReferenceItem], tags=["reference"])
def groups(client: Keitaro) -> list[dict]:
    return client.list_items("groups", type="campaigns")


@router.get("/reference/traffic-sources", response_model=list[ReferenceItem], tags=["reference"])
def traffic_sources(client: Keitaro) -> list[dict]:
    return [x for x in client.list_items("traffic_sources") if x.get("state") == "active"]


@router.get("/offers", response_model=list[ReferenceItem], tags=["offers"])
def offers(
    client: Keitaro,
    q: Annotated[str, Query(max_length=255)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict]:
    query = q.strip().casefold()
    return [
        x
        for x in client.list_items("offers")
        if x.get("state") == "active"
        and (not query or query == str(x["id"]) or query in x["name"].casefold())
    ][:limit]


def replay(operation: CampaignCreation, body: dict, response: Response) -> CampaignCreated:
    if operation.request != body:
        raise HTTPException(409, detail={"code": "idempotency_key_reused"})
    if operation.status == "succeeded":
        response.status_code = 200
        return CampaignCreated.model_validate(operation.result)
    raise HTTPException(
        409,
        detail={
            "code": "creation_requires_review",
            "operation_id": operation.id,
            "status": operation.status,
        },
    )


def require_reference(items: list[dict], item_id: int, label: str) -> dict:
    for item in items:
        if item["id"] == item_id and item.get("state", "active") == "active":
            return item
    raise HTTPException(422, detail={"code": f"invalid_{label}"})


@router.post("/campaigns", response_model=CampaignCreated, status_code=201, tags=["campaigns"])
def create_campaign(
    body: CampaignCreate,
    request: Request,
    response: Response,
    session: Db,
    client: Keitaro,
    idempotency_key: Annotated[UUID, Header()],
) -> CampaignCreated:
    operation_id = str(idempotency_key)
    original = body.model_dump(mode="json")
    existing = session.get(CampaignCreation, operation_id)
    if existing:
        return replay(existing, original, response)

    settings: Settings = request.app.state.settings
    domain_id = body.domain_id or settings.keitaro_domain_id
    group_id = body.group_id or settings.keitaro_group_id
    source_id = body.traffic_source_id or settings.keitaro_traffic_source_id
    if not all((domain_id, group_id, source_id)):
        raise HTTPException(422, detail={"code": "campaign_defaults_missing"})

    # Save intent before any external mutation. The unique key serializes duplicate submissions.
    operation = CampaignCreation(id=operation_id, request=original)
    session.add(operation)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.get(CampaignCreation, operation_id)
        if existing:
            return replay(existing, original, response)
        raise

    def phase(value: str) -> None:
        operation.phase = value
        session.commit()

    try:
        domain = require_reference(client.list_items("domains"), domain_id, "domain")
        require_reference(client.list_items("groups", type="campaigns"), group_id, "group")
        require_reference(client.list_items("traffic_sources"), source_id, "traffic_source")
        try:
            offer = client.get_offer(body.offer_id)
        except KeitaroError as error:
            if error.code == "keitaro_not_found":
                raise HTTPException(422, detail={"code": "invalid_offer"}) from None
            raise
        if offer.get("state") != "active":
            raise HTTPException(422, detail={"code": "invalid_offer"})

        alias = f"adrobot-{idempotency_key.hex}"
        phase("create_campaign")
        remote_id = client.create_campaign(
            {
                "name": body.name,
                "alias": alias,
                "type": "position",
                "state": "disabled",
                "domain_id": domain_id,
                "group_id": str(group_id),
                "traffic_source_id": source_id,
            }
        )
        operation.remote_campaign_id = remote_id
        phase("create_geo_stream")
        common = {
            "campaign_id": remote_id,
            "type": "regular",
            "state": "active",
            "action_type": "http",
            "collect_clicks": True,
            "filter_or": False,
        }
        geo_id = client.create_stream(
            {
                **common,
                "name": f"Geo: {body.country_code} → Google",
                "position": 1,
                "schema": "redirect",
                "action_payload": "https://www.google.com/",
                "filters": [{"name": "country", "mode": "accept", "payload": [body.country_code]}],
            }
        )
        phase("create_offer_stream")
        offer_stream_id = client.create_stream(
            {
                **common,
                "name": "Offer fallback",
                "position": 2,
                "schema": "landings",
                "action_payload": "",
                "filters": [],
                "landings": [],
                "offers": [{"offer_id": body.offer_id, "share": 100, "state": "active"}],
            }
        )
        phase("enable_campaign")
        client.enable_campaign(remote_id)

        campaign = Campaign(keitaro_id=remote_id, name=body.name)
        session.add(campaign)
        session.flush()
        scheme = "https" if domain.get("is_ssl") else "http"
        result = CampaignCreated(
            operation_id=operation_id,
            campaign_id=campaign.id,
            keitaro_id=remote_id,
            name=body.name,
            alias=alias,
            tracking_url=f"{scheme}://{domain['name']}/{alias}",
            stream_ids=[geo_id, offer_stream_id],
        )
        operation.result = result.model_dump(mode="json")
        operation.status = "succeeded"
        operation.phase = "completed"
        session.commit()
        return result
    except HTTPException:
        operation.status = "failed"
        operation.error_code = "invalid_reference"
        session.commit()
        raise
    except KeitaroError as error:
        operation.status = "unknown" if error.uncertain else "failed"
        operation.error_code = error.code
        session.commit()
        raise HTTPException(
            502,
            detail={
                "code": error.code,
                "operation_id": operation.id,
                "status": operation.status,
                "phase": operation.phase,
                "remote_campaign_id": operation.remote_campaign_id,
            },
        ) from None
    except SQLAlchemyError:
        # The last committed phase remains available for manual reconciliation.
        # In particular, an external enable may have succeeded before the local commit failed.
        session.rollback()
        raise HTTPException(
            503,
            detail={"code": "creation_storage_error", "operation_id": operation_id},
        ) from None


@router.get("/campaign-creations/{operation_id}", response_model=CreationStatus, tags=["campaigns"])
def creation_status(operation_id: UUID, session: Db) -> CampaignCreation:
    operation = session.get(CampaignCreation, str(operation_id))
    if operation is None:
        raise HTTPException(404, detail={"code": "creation_not_found"})
    return operation
