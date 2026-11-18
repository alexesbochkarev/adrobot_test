from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from adrobot.db import get_session
from adrobot.models import Campaign, CampaignCreation, Offer, Stream, StreamOffer

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/live", response_model=HealthResponse)
def live() -> HealthResponse:
    return HealthResponse()


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"description": "Database unavailable or migrations missing"}},
)
def ready(session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
    try:
        # An empty database accepting SELECT 1 is not ready to serve application requests.
        session.execute(select(Campaign.id).limit(1))
        session.execute(select(CampaignCreation.id).limit(1))
        session.execute(select(Stream.id).limit(1))
        session.execute(select(Offer.id).limit(1))
        session.execute(select(StreamOffer.stream_id).limit(1))
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable or migrations not applied",
        ) from None
    return HealthResponse()
