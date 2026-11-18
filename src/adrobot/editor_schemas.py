from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Revision = Annotated[int, Field(strict=True, gt=0)]


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: Revision


class AddOfferRequest(EditRequest):
    offer_id: Annotated[int, Field(strict=True, gt=0)]


class PinRequest(EditRequest):
    share: Annotated[int, Field(strict=True, ge=0, le=100)] | None = None


class StreamOfferView(BaseModel):
    offer_id: int  # Keitaro ID
    name: str
    share: int
    pinned: bool
    removed: bool
    is_new: bool


class StreamView(BaseModel):
    id: int
    keitaro_id: int
    name: str
    position: int
    schema_kind: str
    revision: int
    remote_present: bool
    is_dirty: bool
    offers: list[StreamOfferView]


class CampaignStreamsView(BaseModel):
    campaign_id: int
    keitaro_id: int
    editor_revision: int
    sync_locked: bool
    publication_id: str | None = None
    streams: list[StreamView]


class PublicationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    stream_id: int  # Local stream ID
    expected_revision: int
    status: Literal["pending", "succeeded", "failed", "conflict", "unknown"]
    phase: str
    error_code: str | None
    result: StreamView | None
