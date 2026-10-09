import json
import secrets
import ssl
import datetime
import ipaddress
from unittest.mock import AsyncMock, patch

import pytest

from agent.vault_store import VaultStore
from tools import vault_credential_request as consumer

SERVICES = {"fictional": {"url": "https://api.example.test/account"}}


def test_encrypted_handle_consumption_and_response_redaction(tmp_path):
    store = VaultStore(base_dir=tmp_path / "vault")
    secret = secrets.token_urlsafe(40)
    meta = store.add_item("api_key", "fictional", {"value": secret})
    response = {"success": True, "data": {"name": "Example", "api_key": "other-secret",
                                          "echo": "Bearer " + secret}}
    transport = AsyncMock(return_value=response)
    with patch("agent.vault_store.get_vault_store", return_value=store), patch.object(consumer, "fetch", transport):
        result = consumer.request(meta.id, "fictional", SERVICES, lambda: True)
    assert json.loads(result)["success"]
    assert secret not in result and "other-secret" not in result
    assert json.loads(result)["data"]["name"] == "Example"
    transport.assert_awaited_once_with(
        SERVICES["fictional"]["url"], {"Authorization": "Bearer " + secret}
    )
    assert secret.encode() not in (tmp_path / "vault" / "vault.json.enc").read_bytes()


def test_cloudflare_access_uses_profile_scoped_client_id_and_vault_secret(tmp_path):
    store = VaultStore(base_dir=tmp_path / "vault")
    secret = secrets.token_urlsafe(40)
    meta = store.add_item("token", "executor", {"value": secret})
    service = {
        "executor": {
            "url": "https://executor.example.test/.well-known/executor-credential-check",
            "header": "CF-Access-Client-Secret",
            "scheme": "cloudflare_access",
        }
    }
    transport = AsyncMock(
        return_value={
            "success": True,
            "status": 200,
            "data": {"read_only": True, "echo": f"scoped-client-id {secret}"},
        }
    )
    with (
        patch("agent.vault_store.get_vault_store", return_value=store),
        patch("agent.secret_scope.get_secret", return_value="scoped-client-id"),
        patch.object(consumer, "fetch", transport),
    ):
        result = consumer.request(meta.id, "executor", service, lambda: True)
    assert json.loads(result)["success"]
    assert secret not in result
    assert "scoped-client-id" not in result
    transport.assert_awaited_once_with(
        service["executor"]["url"],
        {
            "CF-Access-Client-Id": "scoped-client-id",
            "CF-Access-Client-Secret": secret,
        },
    )
    assert secret.encode() not in (tmp_path / "vault" / "vault.json.enc").read_bytes()


def test_wrong_service_or_inactive_task_never_contacts_network(tmp_path):
    store = VaultStore(base_dir=tmp_path / "vault")
    meta = store.add_item("token", "different", {"value": secrets.token_urlsafe(40)})
    transport = AsyncMock()
    with patch("agent.vault_store.get_vault_store", return_value=store), patch.object(consumer, "fetch", transport):
        assert not json.loads(consumer.request(meta.id, "fictional", SERVICES, lambda: True))["success"]
        assert not json.loads(consumer.request(meta.id, "different", SERVICES, lambda: False))["success"]
    transport.assert_not_called()


@pytest.mark.parametrize("url", ["http://api.example.test", "https://127.0.0.1", "https://[::1]",
                                   "https://u:p@api.example.test", "https://api.example.test/?token=x",
                                   "https://api.example.test:8443", "https://api.example.test/#x"])
def test_unsafe_endpoint_refused(url):
    with pytest.raises(ValueError):
        consumer.binding({"service": {"url": url}}, "service")


@pytest.mark.asyncio
async def test_dns_private_answer_refused():
    resolver = consumer.PublicResolver()
    with patch.object(consumer.DefaultResolver, "resolve", AsyncMock(return_value=[{"host": "127.0.0.1"}])):
        with pytest.raises(ValueError):
            await resolver.resolve("api.example.test", 443)
    await resolver.close()


def test_no_active_gateway_access():
    from gateway.run_turn_secure_login import authenticated_request
    assert not json.loads(authenticated_request("handle", "fictional"))["success"]


@pytest.mark.asyncio
async def test_real_https_transport_does_not_follow_redirects(tmp_path, monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestServer
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fictional-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "test-cert.pem", tmp_path / "test-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    server_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ssl.load_cert_chain(cert_path, key_path)
    client_ssl = ssl.create_default_context(cafile=str(cert_path))
    connector_class = consumer.aiohttp.TCPConnector
    monkeypatch.setattr(consumer.aiohttp, "TCPConnector", lambda **kwargs: connector_class(ssl=client_ssl, **kwargs))
    credential = secrets.token_urlsafe(40)
    contacted = []

    async def account(request):
        contacted.append("account")
        assert request.headers["Authorization"] == "Bearer " + credential
        return web.json_response({"name": "Fictional service", "echo": credential})

    async def redirect(request):
        raise web.HTTPFound("/account")

    app = web.Application()
    app.router.add_get("/account", account)
    app.router.add_get("/redirect", redirect)
    server = TestServer(app, scheme="https")
    await server.start_server(ssl=server_ssl)
    try:
        headers = {"Authorization": "Bearer " + credential}
        result = await consumer.fetch(str(server.make_url("/account")), headers)
        safe = json.dumps(consumer.sanitise(result, credential))
        assert result["success"] and credential not in safe
        refused = await consumer.fetch(str(server.make_url("/redirect")), headers)
        assert not refused["success"] and refused["status"] == 302
        assert contacted == ["account"]
    finally:
        await server.close()
