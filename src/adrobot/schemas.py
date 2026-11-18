from typing import Literal

import pycountry
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    country_code: str = Field(min_length=2, max_length=2)
    offer_id: PositiveInt
    domain_id: PositiveInt | None = None
    group_id: PositiveInt | None = None
    traffic_source_id: PositiveInt | None = None

    @field_validator("country_code")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        value = value.upper()
        if pycountry.countries.get(alpha_2=value) is None:
            raise ValueError("Use an ISO 3166-1 alpha-2 country code")
        return value


class ReferenceItem(BaseModel):
    id: int
    name: str


class CampaignCreated(BaseModel):
    operation_id: str
    campaign_id: int
    keitaro_id: int
    name: str
    alias: str
    tracking_url: str
    stream_ids: list[int]


class CreationStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: Literal["pending", "succeeded", "failed", "unknown"]
    phase: str
    remote_campaign_id: int | None
    error_code: str | None
    result: CampaignCreated | None
