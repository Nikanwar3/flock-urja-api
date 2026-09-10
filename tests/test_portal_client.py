import hashlib
import hmac

import httpx
import pytest
import respx

from app.config import Settings
from app.portal_client import PortalClient
from app.portal_errors import PortalAuthError, PortalUnavailableError

BASE = "https://urja-ops.test"
SETTINGS = Settings(portal_base_url=BASE, portal_email="a@b.com", portal_password="pw")


def _mock_login_success(mock):
    mock.post(f"{BASE}/login").mock(
        return_value=httpx.Response(
            200,
            json={"type": "redirect", "status": 303, "location": "/meters"},
            headers={"set-cookie": "__Secure-better-auth.session_token=abc; Max-Age=3600; Path=/"},
        )
    )


@pytest.mark.asyncio
@respx.mock
async def test_login_success_marks_session_active():
    _mock_login_success(respx)
    client = PortalClient(SETTINGS)
    await client._ensure_session()
    assert client.session_active() is True
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_login_failure_raises_auth_error():
    respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(
            200, json={"type": "failure", "status": 401, "data": "Invalid email or password."}
        )
    )
    client = PortalClient(SETTINGS)
    with pytest.raises(PortalAuthError):
        await client._ensure_session()
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_all_meters_signs_request_correctly():
    _mock_login_success(respx)
    respx.get(f"{BASE}/portal/keys").mock(return_value=httpx.Response(200, json={"data": {"signingSecret": "s3cr3t"}}))

    captured = {}

    def export_responder(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"data": [{"meterId": "J1"}], "total": 1})

    respx.get(f"{BASE}/portal/export").mock(side_effect=export_responder)

    client = PortalClient(SETTINGS)
    data = await client.fetch_all_meters()
    assert data == [{"meterId": "J1"}]

    timestamp = captured["headers"]["x-timestamp"]
    expected_sig = hmac.new(
        b"s3cr3t", f"GET\n/portal/export\npage=1\n{timestamp}".encode(), hashlib.sha256
    ).hexdigest()
    assert captured["headers"]["x-signature"] == expected_sig
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_expired_session_triggers_one_relogin_and_retry():
    _mock_login_success(respx)
    respx.get(f"{BASE}/portal/dts").mock(
        side_effect=[
            httpx.Response(401, json={"error": "unauthorized"}),
            httpx.Response(200, json={"data": [{"code": "DT-001"}], "total": 1}),
        ]
    )
    client = PortalClient(SETTINGS)
    result = await client.fetch_all_transformers()
    assert result == [{"code": "DT-001"}]
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_network_error_becomes_portal_unavailable():
    _mock_login_success(respx)
    respx.get(f"{BASE}/portal/dts").mock(side_effect=httpx.ConnectError("boom"))
    client = PortalClient(SETTINGS)
    with pytest.raises(PortalUnavailableError):
        await client.fetch_all_transformers()
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_5xx_becomes_portal_unavailable():
    _mock_login_success(respx)
    respx.get(f"{BASE}/portal/dts").mock(return_value=httpx.Response(503))
    client = PortalClient(SETTINGS)
    with pytest.raises(PortalUnavailableError):
        await client.fetch_all_transformers()
    await client.aclose()
