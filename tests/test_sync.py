import json
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from adrobot.config import Settings
from adrobot.db import create_db_engine
from adrobot.keitaro import KeitaroClient
from adrobot.main import create_app
from adrobot.models import Campaign, Publication, Stream
from adrobot.sync import SyncError, guard_campaign, snapshot


def test_empty_comments_are_equivalent_but_real_comments_are_not():
    data = Tracker().streams[200]
    data["comments"] = None
    before = snapshot(data, 100)
    data["comments"] = ""
    assert snapshot(data, 100) == before
    data["comments"] = "Changed by user"
    assert snapshot(data, 100) != before


class Tracker:
    def __init__(self):
        self.requests = []
        self.put_mode = "success"
        self.hook = None
        self.offer_state = "active"
        self.fail_verify = False
        self.after_write = False
        self.streams = {
            199: {
                "id": 199,
                "campaign_id": 100,
                "position": 1,
                "name": "Geo",
                "schema": "redirect",
                "state": "active",
                "type": "regular",
                "action_type": "http",
                "action_payload": "https://google.com",
                "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}],
                "offers": [],
                "landings": [],
                "updated_at": "old",
            },
            200: {
                "id": 200,
                "campaign_id": 100,
                "position": 2,
                "name": "Offers",
                "schema": "landings",
                "state": "active",
                "type": "regular",
                "action_type": "http",
                "action_payload": "",
                "filters": [],
                "landings": [],
                "offers": [
                    {"offer_id": 10, "share": 50, "state": "active", "id": 991},
                    {"offer_id": 20, "share": 50, "state": "active", "id": 992},
                ],
                "updated_at": "old",
            },
        }

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix("/admin_api/v1/")
        if self.hook:
            hook, self.hook = self.hook, None
            hook(request)
        if request.method == "GET":
            if path == "campaigns":
                return httpx.Response(
                    200, json=[{"id": 100, "name": "Campaign", "state": "active"}]
                )
            if path == "campaigns/100":
                return httpx.Response(200, json={"id": 100, "name": "Campaign", "state": "active"})
            if path == "campaigns/100/streams":
                return httpx.Response(200, json=list(self.streams.values()))
            if path == "offers":
                return httpx.Response(
                    200, json=[{"id": i, "name": f"Offer {i}"} for i in (10, 20, 30)]
                )
            if path.startswith("offers/"):
                offer_id = int(path.split("/")[1])
                if offer_id not in (10, 20, 30):
                    return httpx.Response(404, json={})
                return httpx.Response(
                    200,
                    json={"id": offer_id, "name": f"Offer {offer_id}", "state": self.offer_state},
                )
            if path.startswith("streams/"):
                if self.fail_verify and self.after_write:
                    raise httpx.ReadTimeout("verification failed", request=request)
                remote_id = int(path.split("/")[1])
                if remote_id not in self.streams:
                    return httpx.Response(404, json={})
                return httpx.Response(200, json=self.streams[remote_id])
        if request.method == "PUT" and path == "streams/200":
            payload = json.loads(request.content)
            assert set(payload) == {"offers"}, "Never overwrite filters or other stream settings"
            if self.put_mode == "reject":
                return httpx.Response(400, json={"private": "internal upstream data"})
            if self.put_mode == "timeout_before":
                raise httpx.ReadTimeout("timeout", request=request)
            self.streams[200]["offers"] = payload["offers"]
            self.after_write = True
            self.streams[200]["updated_at"] = "new"
            if self.put_mode == "timeout_after":
                raise httpx.ReadTimeout("timeout", request=request)
            if self.put_mode == "mismatch":
                self.streams[200]["filters"] = [{"name": "unexpected"}]
            return httpx.Response(200, json=self.streams[200])
        raise AssertionError(f"Unexpected request: {request.method} {path}")


@pytest.fixture
def api(migrated_database):
    tracker = Tracker()
    app = create_app(Settings(_env_file=None, database_url=migrated_database))
    with (
        httpx.Client(
            base_url="https://example.test/admin_api/v1/", transport=httpx.MockTransport(tracker)
        ) as http,
        TestClient(app) as client,
    ):
        app.state.keitaro = KeitaroClient(http)
        yield client, tracker


def fetch(client):
    response = client.post("/api/v1/campaigns/100/fetch")
    assert response.status_code == 200, response.text
    return next(x for x in response.json()["streams"] if x["keitaro_id"] == 200)


def edit(client, action, revision, offer=10, **fields):
    return client.post(
        f"/api/v1/streams/200/offers/{offer}/{action}",
        json={"expected_revision": revision, **fields},
    )


def push(client, revision, key=None):
    return client.post(
        "/api/v1/streams/200/push",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"expected_revision": revision},
    )


def cached(client):
    response = client.get("/api/v1/campaigns/100/streams")
    assert response.status_code == 200, response.text
    return response.json()


def test_full_add_cancel_remove_push_restore_flow(api):
    client, tracker = api
    initial = fetch(client)
    assert initial["revision"] == 1 and not initial["is_dirty"]
    assert client.get("/api/v1/campaigns").json() == [{"id": 100, "name": "Campaign"}]
    added = client.post("/api/v1/streams/200/offers", json={"expected_revision": 1, "offer_id": 30})
    assert added.status_code == 200, added.text
    assert [x["share"] for x in added.json()["offers"]] == [34, 33, 33]
    assert len(tracker.streams[200]["offers"]) == 2
    assert client.post("/api/v1/campaigns/100/fetch").status_code == 409
    canceled = client.post("/api/v1/streams/200/cancel", json={"expected_revision": 2})
    assert canceled.status_code == 200 and not canceled.json()["is_dirty"]
    assert len(canceled.json()["offers"]) == 2
    removed = edit(client, "remove", 3, offer=20)
    assert removed.status_code == 200, removed.text
    assert removed.json()["offers"][1]["removed"]
    assert tracker.streams[200]["offers"][1]["offer_id"] == 20
    published = push(client, 4)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "succeeded"
    assert not published.json()["result"]["is_dirty"]
    assert tracker.streams[200]["offers"] == [{"offer_id": 10, "share": 100, "state": "active"}]
    restored = edit(client, "restore", 5, offer=20)
    assert restored.status_code == 200, restored.text
    assert [x["share"] for x in restored.json()["offers"]] == [50, 50]
    assert push(client, 6).status_code == 200
    assert len(tracker.streams[200]["offers"]) == 2


def test_fetch_archives_external_deletion_and_keeps_archive_on_repeated_fetch(api):
    client, tracker = api
    fetch(client)
    tracker.streams[200]["offers"] = [{"offer_id": 10, "share": 100, "state": "active"}]
    updated = fetch(client)
    assert updated["offers"][1]["removed"] and updated["offers"][1]["share"] == 0
    assert not updated["is_dirty"]
    assert fetch(client)["offers"][1]["removed"]


def test_pins_survive_fetch_only_while_remote_share_is_unchanged(api):
    client, tracker = api
    fetch(client)
    assert edit(client, "pin", 1, share=25).status_code == 200
    assert push(client, 2).status_code == 200
    synced = fetch(client)
    assert synced["offers"][0]["pinned"] and synced["offers"][0]["share"] == 25
    tracker.streams[200]["offers"][0]["share"] = 40
    tracker.streams[200]["offers"][1]["share"] = 60
    updated = fetch(client)
    assert not updated["offers"][0]["pinned"]
    assert updated["offers"][0]["share"] == 40


@pytest.mark.parametrize("field", ["offers", "filters", "name"])
def test_external_conflict_keeps_draft_and_performs_no_put(api, field):
    client, tracker = api
    fetch(client)
    assert edit(client, "pin", 1, share=25).status_code == 200
    if field == "offers":
        tracker.streams[200]["offers"][0]["share"] = 40
        tracker.streams[200]["offers"][1]["share"] = 60
    elif field == "filters":
        tracker.streams[200]["filters"] = [{"name": "country"}]
    else:
        tracker.streams[200]["name"] = "Changed externally"
    response = push(client, 2)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["publication_status"] == "conflict"
    assert not any(r.method == "PUT" for r in tracker.requests)
    assert not cached(client)["sync_locked"]
    assert cached(client)["streams"][1]["is_dirty"]


def test_push_idempotency_and_stale_revision(api):
    client, tracker = api
    fetch(client)
    assert edit(client, "pin", 1).status_code == 200
    assert edit(client, "remove", 1, offer=20).status_code == 409
    key = str(uuid4())
    response = push(client, 2, key)
    assert response.status_code == 200, response.text
    count = len(tracker.requests)
    assert push(client, 2, key).json() == response.json()
    assert len(tracker.requests) == count
    assert push(client, 3, key).status_code == 409


def test_known_write_rejection_releases_lock_but_keeps_draft(api):
    client, tracker = api
    fetch(client)
    edit(client, "pin", 1, share=25)
    tracker.put_mode = "reject"
    response = push(client, 2)
    assert response.status_code == 502
    assert response.json()["detail"]["publication_status"] == "failed"
    assert not cached(client)["sync_locked"]
    assert cached(client)["streams"][1]["is_dirty"]
    assert "internal" not in response.text


def test_timeout_after_write_locks_edits_and_reconciles_without_second_put(api):
    client, tracker = api
    fetch(client)
    edit(client, "pin", 1, share=25)
    tracker.put_mode = "timeout_after"
    key = str(uuid4())
    response = push(client, 2, key)
    assert response.status_code == 502, response.text
    assert response.json()["detail"]["publication_status"] == "unknown"
    assert cached(client)["sync_locked"]
    assert cached(client)["publication_id"] == key
    assert client.post("/api/v1/campaigns/100/fetch").status_code == 409
    assert edit(client, "unpin", 2).status_code == 409
    assert (
        client.post("/api/v1/streams/200/cancel", json={"expected_revision": 2}).status_code == 409
    )
    assert push(client, 2, key).status_code == 409
    result = client.post(f"/api/v1/publications/{key}/reconcile")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "succeeded"
    assert not cached(client)["sync_locked"]
    assert not result.json()["result"]["is_dirty"]
    assert sum(r.method == "PUT" for r in tracker.requests) == 1


@pytest.mark.parametrize("mode", ["timeout_before", "mismatch"])
def test_unconfirmed_publication_remains_locked(api, mode):
    client, tracker = api
    fetch(client)
    edit(client, "pin", 1, share=25)
    tracker.put_mode = mode
    key = str(uuid4())
    assert push(client, 2, key).status_code == 502
    assert client.post(f"/api/v1/publications/{key}/reconcile").status_code == 409
    assert cached(client)["sync_locked"]
    assert cached(client)["streams"][1]["is_dirty"]


def test_missing_remote_stream_is_retained_as_unavailable(api):
    client, tracker = api
    fetch(client)
    del tracker.streams[200]
    response = client.post("/api/v1/campaigns/100/fetch")
    assert response.status_code == 200
    missing = next(x for x in response.json()["streams"] if x["keitaro_id"] == 200)
    assert not missing["remote_present"]
    assert all(x["removed"] for x in missing["offers"])
    assert edit(client, "restore", missing["revision"]).status_code == 409


def test_fetch_does_not_parse_redirect_content(api):
    client, tracker = api
    tracker.streams[199]["offers"] = "opaque non-offer content"
    fetch(client)
    redirect = cached(client)["streams"][0]
    assert redirect["offers"] == [] and redirect["schema_kind"] == "redirect"


def test_malformed_fetch_does_not_partially_update_local_state(api):
    client, tracker = api
    original = fetch(client)
    tracker.streams[200]["offers"][0]["share"] = 99
    assert client.post("/api/v1/campaigns/100/fetch").status_code == 422
    assert cached(client)["streams"][1] == original


def test_edit_during_fetch_causes_fetch_to_reject_stale_result(api):
    client, tracker = api
    fetch(client)
    tracker.hook = lambda _request: edit(client, "pin", 1, share=25)
    response = client.post("/api/v1/campaigns/100/fetch")
    assert response.status_code == 409, response.text
    local = cached(client)["streams"][1]
    assert local["is_dirty"] and local["offers"][0]["share"] == 25


def test_campaign_guard_rejects_competing_sessions(migrated_database):
    engine = create_db_engine(migrated_database)
    try:
        with Session(engine) as session:
            campaign = Campaign(keitaro_id=100, name="Test")
            session.add(campaign)
            session.commit()
        with Session(engine) as first, Session(engine) as second:
            a = first.scalar(select(Campaign))
            b = second.scalar(select(Campaign))
            guard_campaign(first, a, token=str(uuid4()))
            first.commit()
            with pytest.raises(SyncError):
                guard_campaign(second, b)
            second.rollback()
    finally:
        engine.dispose()


def test_upgrade_and_downgrade_preserve_existing_editor_data(database_url):
    config = Config("alembic.ini")
    command.upgrade(config, "0003")
    engine = create_db_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO campaigns(id,keitaro_id,name) VALUES(1,100,'Test')")
            )
            connection.execute(text("INSERT INTO offers(id,keitaro_id,name) VALUES(1,10,'Offer')"))
            connection.execute(
                text(
                    "INSERT INTO streams(id,keitaro_id,campaign_id,name,"
                    "position,schema_kind,revision) "
                    "VALUES(1,200,1,'Flow',1,'landings',1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO stream_offers(stream_id,offer_id,share,pinned,removed,"
                    "published_share,published_pinned,published_removed) "
                    "VALUES(1,1,100,1,0,100,1,0)"
                )
            )
        command.upgrade(config, "head")
        with Session(engine) as session:
            stream = session.get(Stream, 1)
            assert stream.remote_present and stream.offers[0].pinned
            assert stream.campaign.editor_revision == 1
        command.downgrade(config, "0003")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM streams")).scalar() == 1
            assert connection.execute(text("SELECT share FROM stream_offers")).scalar() == 100
        command.upgrade(config, "head")
        command.check(config)
    finally:
        engine.dispose()


def test_verification_read_failure_keeps_lock_and_can_be_reconciled(api):
    client, tracker = api
    fetch(client)
    edit(client, "pin", 1, share=25)
    tracker.fail_verify = True
    key = str(uuid4())
    assert push(client, 2, key).status_code == 502
    assert cached(client)["sync_locked"]
    tracker.fail_verify = False
    assert client.post(f"/api/v1/publications/{key}/reconcile").status_code == 200
    assert sum(r.method == "PUT" for r in tracker.requests) == 1


def test_database_failure_after_put_can_be_reconciled(api):
    client, tracker = api
    fetch(client)
    edit(client, "pin", 1, share=25)
    key = str(uuid4())

    def fail_confirmation(session, _context, _instances):
        if any(isinstance(x, Publication) and x.status == "succeeded" for x in session.dirty):
            raise OperationalError("UPDATE", {}, Exception("simulated write failure"))

    event.listen(Session, "before_flush", fail_confirmation)
    try:
        assert push(client, 2, key).status_code == 503
    finally:
        event.remove(Session, "before_flush", fail_confirmation)
    status = client.get(f"/api/v1/publications/{key}").json()
    assert status["status"] == "pending" and status["phase"] == "verifying"
    assert cached(client)["sync_locked"]
    assert client.post(f"/api/v1/publications/{key}/reconcile").status_code == 200
    assert sum(r.method == "PUT" for r in tracker.requests) == 1


def test_edit_and_fetch_blocked_while_push_is_running(api):
    client, tracker = api
    fetch(client)
    edit(client, "pin", 1, share=25)
    observed = []

    def attempt_edit(_request):
        observed.append(edit(client, "unpin", 2).status_code)
        observed.append(client.post("/api/v1/campaigns/100/fetch").status_code)

    tracker.hook = attempt_edit
    assert push(client, 2).status_code == 200
    assert observed == [409, 409]


def test_unavailable_offer_fails_before_put(api):
    client, tracker = api
    fetch(client)
    edit(client, "pin", 1, share=25)
    tracker.offer_state = "deleted"
    assert push(client, 2).status_code == 422
    assert not cached(client)["sync_locked"]
    assert not any(r.method == "PUT" for r in tracker.requests)


@pytest.mark.parametrize("share", [25.5, True, "25", -1, 101])
def test_pin_strict_validation(api, share):
    client, _tracker = api
    fetch(client)
    assert edit(client, "pin", 1, share=share).status_code == 422
    assert not cached(client)["streams"][1]["is_dirty"]


def test_unknown_resources_and_noop_push(api):
    client, _tracker = api
    assert client.get("/api/v1/campaigns/100/streams").status_code == 404
    assert client.get(f"/api/v1/publications/{uuid4()}").status_code == 404
    fetch(client)
    assert push(client, 1).status_code == 409
