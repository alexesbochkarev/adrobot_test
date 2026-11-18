import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from adrobot.config import Settings
from adrobot.keitaro import KeitaroClient, get_keitaro
from adrobot.main import create_app
from adrobot.models import Campaign


class FakeKeitaro:
    def __init__(self):
        self.requests = []
        self.fail_stream = False
        self.timeout_enable = False
        self.timeout_create = False
        self.offer_exists = True
        self.stream_count = 0

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix("/admin_api/v1/")
        if request.method == "GET":
            fixtures = {
                "domains": [
                    {"id": 1, "name": "track.example.test", "state": "active", "is_ssl": True}
                ],
                "groups": [{"id": 2, "name": "Tests", "type": "campaigns"}],
                "traffic_sources": [{"id": 3, "name": "Tests", "state": "active"}],
                "offers/4": {"id": 4, "name": "Offer", "state": "active"},
                "offers": [
                    {"id": 4, "name": "Offer", "state": "active", "secret": "hidden"},
                    {"id": 5, "name": "Old", "state": "deleted"},
                ],
            }
            if path == "groups":
                assert request.url.params["type"] == "campaigns"
            if path == "offers/4" and not self.offer_exists:
                return httpx.Response(404, json={})
            return httpx.Response(200, json=fixtures[path])
        if path == "campaigns":
            if self.timeout_create:
                raise httpx.ReadTimeout("timeout", request=request)
            return httpx.Response(200, json={"id": 100})
        if path == "streams":
            self.stream_count += 1
            if self.fail_stream and self.stream_count == 2:
                return httpx.Response(400, json={"message": "bad stream"})
            return httpx.Response(200, json={"id": 200 + self.stream_count})
        if path == "campaigns/100/enable":
            if self.timeout_enable:
                raise httpx.ReadTimeout("timeout", request=request)
            return httpx.Response(200, json={"id": 100, "state": "active"})
        raise AssertionError(f"Unexpected upstream request: {request.method} {path}")


@pytest.fixture
def api(migrated_database):
    fake = FakeKeitaro()
    settings = Settings(
        _env_file=None,
        database_url=migrated_database,
        keitaro_domain_id=1,
        keitaro_group_id=2,
        keitaro_traffic_source_id=3,
    )
    app = create_app(settings)
    with httpx.Client(
        base_url="https://example.test/admin_api/v1/", transport=httpx.MockTransport(fake)
    ) as http:
        app.dependency_overrides[get_keitaro] = lambda: KeitaroClient(http)
        with TestClient(app) as client:
            yield client, fake


def create(client, key, **changes):
    return client.post(
        "/api/v1/campaigns",
        headers={"Idempotency-Key": key},
        json={"name": "Test", "country_code": "au", "offer_id": 4, **changes},
    )


def test_creation_and_idempotent_replay(api):
    client, fake = api
    key = str(uuid4())
    response = create(client, key)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["keitaro_id"] == 100
    assert data["stream_ids"] == [201, 202]
    assert data["tracking_url"].startswith("https://track.example.test/adrobot-")
    writes = [r for r in fake.requests if r.method == "POST"]
    assert len(writes) == 4
    campaign, geo, offer = [json.loads(r.content) for r in writes[:3]]
    assert campaign["state"] == "disabled"
    assert campaign["type"] == "position"
    assert (campaign["domain_id"], campaign["group_id"], campaign["traffic_source_id"]) == (
        1,
        "2",
        3,
    )
    assert geo["position"] == 1
    assert geo["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU"]}]
    assert geo["action_payload"] == "https://www.google.com/"
    assert offer["position"] == 2 and offer["filters"] == []
    assert offer["offers"] == [{"offer_id": 4, "share": 100, "state": "active"}]
    before = len(fake.requests)
    repeated = create(client, key)
    assert repeated.status_code == 200 and repeated.json() == data
    assert len(fake.requests) == before
    status = client.get(f"/api/v1/campaign-creations/{key}").json()
    assert status["status"] == "succeeded"
    assert status["result"] == data
    assert create(client, key, name="Different").status_code == 409
    assert len(fake.requests) == before


def test_stream_failure_preserves_disabled_campaign_for_review(api):
    client, fake = api
    fake.fail_stream = True
    key = str(uuid4())
    response = create(client, key)
    assert response.status_code == 502
    assert response.json()["detail"]["remote_campaign_id"] == 100
    status = client.get(f"/api/v1/campaign-creations/{key}").json()
    assert status["status"] == "failed"
    assert status["phase"] == "create_offer_stream"
    assert not any("enable" in r.url.path for r in fake.requests)
    before = len(fake.requests)
    assert create(client, key).status_code == 409
    assert len(fake.requests) == before


def test_timeout_on_enable_is_unknown_not_retried(api):
    client, fake = api
    fake.timeout_enable = True
    key = str(uuid4())
    assert create(client, key).status_code == 502
    status = client.get(f"/api/v1/campaign-creations/{key}").json()
    assert status["status"] == "unknown"
    assert status["phase"] == "enable_campaign"
    assert status["remote_campaign_id"] == 100
    before = len(fake.requests)
    assert create(client, key).status_code == 409
    assert len(fake.requests) == before


@pytest.mark.parametrize(
    "changes", [{"name": " "}, {"country_code": "ZZ"}, {"offer_id": 0}, {"domain_id": -1}]
)
def test_bad_input_rejected_without_external_requests(api, changes):
    client, fake = api
    assert create(client, str(uuid4()), **changes).status_code == 422
    assert fake.requests == []


def test_inaccessible_offer_does_not_create_campaign(api):
    client, fake = api
    fake.offer_exists = False
    assert create(client, str(uuid4())).status_code == 422
    assert all(r.method == "GET" for r in fake.requests)


def test_invalid_reference_does_not_create_campaign(api):
    client, fake = api
    assert create(client, str(uuid4()), domain_id=99).status_code == 422
    assert all(r.method == "GET" for r in fake.requests)


def test_offer_search_filters_deleted_and_private_fields(api):
    client, _fake = api
    assert client.get("/api/v1/offers?q=4").json() == [{"id": 4, "name": "Offer"}]
    assert client.get("/api/v1/offers?q=oFf").json() == [{"id": 4, "name": "Offer"}]
    assert client.get("/api/v1/offers?q=Old").json() == []


def test_missing_key_rejected(api):
    client, fake = api
    response = client.post(
        "/api/v1/campaigns", json={"name": "Test", "country_code": "AU", "offer_id": 4}
    )
    assert response.status_code == 422
    assert fake.requests == []


def test_timeout_before_campaign_id_is_known(api):
    client, fake = api
    fake.timeout_create = True
    key = str(uuid4())
    assert create(client, key).status_code == 502
    status = client.get(f"/api/v1/campaign-creations/{key}").json()
    assert status["status"] == "unknown"
    assert status["phase"] == "create_campaign"
    assert status["remote_campaign_id"] is None
    before = len(fake.requests)
    assert create(client, key).status_code == 409
    assert len(fake.requests) == before


def test_local_failure_after_remote_success_preserves_journal(api):
    client, fake = api
    key = str(uuid4())

    def fail_campaign_insert(session, _context, _instances):
        if any(isinstance(item, Campaign) for item in session.new):
            raise OperationalError("INSERT", {}, Exception("simulated storage failure"))

    event.listen(Session, "before_flush", fail_campaign_insert)
    try:
        response = create(client, key)
    finally:
        event.remove(Session, "before_flush", fail_campaign_insert)
    assert response.status_code == 503
    assert response.json()["detail"]["operation_id"] == key
    status = client.get(f"/api/v1/campaign-creations/{key}").json()
    assert status["status"] == "pending"
    assert status["phase"] == "enable_campaign"
    assert status["remote_campaign_id"] == 100
    before = len(fake.requests)
    assert create(client, key).status_code == 409
    assert len(fake.requests) == before


def test_missing_keitaro_configuration(migrated_database):
    app = create_app(Settings(_env_file=None, database_url=migrated_database))
    with TestClient(app) as client:
        response = client.get("/api/v1/reference/domains")
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "keitaro_not_configured"}}
