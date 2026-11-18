"""Explicit live smoke test: creates one prefixed campaign and disables it in finally."""

import argparse
from uuid import uuid4

from fastapi.testclient import TestClient

from adrobot.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", required=True)
    args = parser.parse_args()
    if not args.run_live:
        return
    operation_id = str(uuid4())
    name = f"test_bochkarev_smoke_{operation_id[:8]}"
    alias = "adrobot-" + operation_id.replace("-", "")
    app = create_app()
    with TestClient(app) as client:
        upstream = app.state.keitaro
        remote_id = None

        def call(method, path, expected=200, **kwargs):
            response = client.request(method, "/api/v1" + path, **kwargs)
            if response.status_code != expected:
                raise RuntimeError(f"{path}: {response.status_code} {response.json()}")
            return response.json()

        try:
            offers = call("GET", "/offers")
            assert offers, "No available offers"
            offer_id = offers[0]["id"]
            body = {"name": name, "country_code": "AU", "offer_id": offer_id}
            headers = {"Idempotency-Key": operation_id}
            print("Creating", name, "operation", operation_id, flush=True)
            created = call("POST", "/campaigns", expected=201, json=body, headers=headers)
            remote_id = created["keitaro_id"]
            print("Campaign", remote_id, flush=True)
            assert call("POST", "/campaigns", json=body, headers=headers) == created
            fetched = call("POST", f"/campaigns/{remote_id}/fetch")
            stream = next(x for x in fetched["streams"] if x["schema_kind"] == "landings")
            sid = stream["keitaro_id"]
            before = upstream.get_stream(sid)
            geo = next(x for x in upstream.get_streams(remote_id) if x["schema"] == "redirect")
            assert geo["position"] < before["position"]
            assert geo["filters"][0]["payload"] == ["AU"]
            assert before["offers"][0]["share"] == 100
            for action in ("pin", "unpin"):
                stream = call(
                    "POST",
                    f"/streams/{sid}/offers/{offer_id}/{action}",
                    json={"expected_revision": stream["revision"]},
                )
                push_body = {"expected_revision": stream["revision"]}
                push_headers = {"Idempotency-Key": str(uuid4())}
                result = call("POST", f"/streams/{sid}/push", json=push_body, headers=push_headers)
                assert result["status"] == "succeeded"
                assert (
                    call("POST", f"/streams/{sid}/push", json=push_body, headers=push_headers)
                    == result
                )
                stream = result["result"]
                assert not stream["is_dirty"]
            after = upstream.get_stream(sid)
            for field in (
                "filters",
                "landings",
                "schema",
                "position",
                "action_type",
                "action_payload",
            ):
                assert before[field] == after[field], field
            assert len(after["offers"]) == 1 and after["offers"][0]["share"] == 100
            call("POST", f"/campaigns/{remote_id}/fetch")
            print("PASS: create, replay, Fetch, pin/unpin, Push, replay, readback", flush=True)
            print(
                "Single available offer: multi-offer changes remain covered by mocks.", flush=True
            )
        finally:
            # Recover a created ID after a lost response; never touch pre-existing campaigns.
            if remote_id is None and upstream is not None:
                matches = [
                    x
                    for x in upstream.list_items("campaigns")
                    if x.get("alias") == alias and x.get("name") == name
                ]
                if len(matches) == 1:
                    remote_id = matches[0]["id"]
            if remote_id is not None:
                owned = upstream.get_campaign(remote_id)
                assert owned["alias"] == alias and owned["name"] == name
                upstream.request("POST", f"campaigns/{remote_id}/disable")
                assert upstream.get_campaign(remote_id)["state"] == "disabled"
                print("Disabled test campaign", remote_id, name, flush=True)


if __name__ == "__main__":
    main()
