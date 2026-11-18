import httpx
import pytest

from adrobot.keitaro import KeitaroClient, KeitaroError


@pytest.mark.parametrize(
    ("status", "code", "uncertain"),
    [
        (401, "keitaro_access_denied", False),
        (403, "keitaro_access_denied", False),
        (404, "keitaro_not_found", False),
        (422, "keitaro_request_rejected", False),
        (429, "keitaro_rate_limited", True),
        (500, "keitaro_server_error", True),
        (302, "keitaro_request_rejected", True),
    ],
)
def test_error_mapping_does_not_leak_upstream_body(status, code, uncertain):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status, text="private upstream details", headers={"Location": "/login"}
        )

    with httpx.Client(
        base_url="https://example.test/", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(KeitaroError) as caught:
            KeitaroClient(http).request("POST", "campaigns", json={})
    assert caught.value.code == code
    assert caught.value.uncertain is uncertain
    assert "private" not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_timeout_is_not_retried(method):
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("private error", request=request)

    with httpx.Client(
        base_url="https://example.test/", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(KeitaroError) as caught:
            KeitaroClient(http).request(method, "campaigns")
    assert caught.value.code == "keitaro_timeout"
    assert caught.value.uncertain is (method == "POST")
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [None, [], {}, {"id": -1}, {"id": "1"}])
def test_invalid_creation_response_requires_review(payload):
    def handler(_request):
        return httpx.Response(200, json=payload)

    with httpx.Client(
        base_url="https://example.test/", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(KeitaroError) as caught:
            KeitaroClient(http).create_campaign({})
    assert caught.value.uncertain


def test_api_key_sent_only_in_header():
    def handler(request):
        assert request.headers["Api-Key"] == "test-key"
        assert "test-key" not in str(request.url)
        return httpx.Response(200, json=[])

    with httpx.Client(
        base_url="https://example.test/admin_api/v1/",
        headers={"Api-Key": "test-key"},
        transport=httpx.MockTransport(handler),
    ) as http:
        assert KeitaroClient(http).list_items("groups", type="campaigns") == []


@pytest.mark.parametrize("as_list", [False, True])
def test_enable_accepts_object_or_array(as_list):
    data = {"id": 123, "state": "active"}
    with httpx.Client(
        base_url="https://example.test/",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=[data] if as_list else data)
        ),
    ) as http:
        KeitaroClient(http).enable_campaign(123)
