"""Read-only, owner-configured vault credential consumers; no arbitrary URL tool."""
import asyncio
import base64
import ipaddress
import json
import re
from urllib.parse import quote, urlsplit

import aiohttp
from aiohttp.resolver import DefaultResolver

LIMIT = 65536
SECRET_FIELD = re.compile(r"password|secret|token|api.?key|authorization|cookie|credential", re.I)


class PublicResolver(DefaultResolver):
    async def resolve(self, host, port=0, family=0):
        addresses = await super().resolve(host, port, family)
        if not addresses or any(not ipaddress.ip_address(a["host"]).is_global for a in addresses):
            raise ValueError("Private destinations are not allowed")
        return addresses  # Connector uses these vetted addresses, not another DNS lookup.


def binding(services, name):
    value = services.get(name) if isinstance(services, dict) and isinstance(name, str) else None
    if not isinstance(value, dict):
        raise ValueError("Configure the service first")
    parsed = urlsplit(value.get("url", ""))
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.query or parsed.port not in (None, 443)):
        raise ValueError("Use a fixed HTTPS endpoint without embedded credentials")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private destinations are not allowed")
    header, scheme = value.get("header", "Authorization"), value.get("scheme", "bearer")
    if scheme == "cloudflare_access":
        if header != "CF-Access-Client-Secret":
            raise ValueError("Unsupported authentication binding")
    elif header not in ("Authorization", "X-API-Key", "Api-Key", "api-key") or scheme not in ("bearer", "raw"):
        raise ValueError("Unsupported authentication binding")
    return value["url"], header, scheme


async def fetch(url, headers):
    connector = aiohttp.TCPConnector(resolver=PublicResolver())
    async with aiohttp.ClientSession(connector=connector, trust_env=False,
                                     timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.get(url, headers=headers, allow_redirects=False) as response:
            if response.status != 200 or response.content_type != "application/json":
                return {"success": False, "status": response.status,
                        "error": "The service did not return a successful JSON response."}
            body = bytearray()
            async for chunk in response.content.iter_chunked(4096):
                body.extend(chunk)
                if len(body) > LIMIT:
                    raise ValueError("Response too large")
            return {"success": True, "status": response.status, "data": json.loads(body)}


def sanitise(value, secret, extra_secrets=()):
    if isinstance(value, dict):
        return {sanitise(str(key), secret, extra_secrets): "[REDACTED]" if SECRET_FIELD.search(str(key)) else sanitise(item, secret, extra_secrets)
                for key, item in value.items()}
    if isinstance(value, list):
        return [sanitise(item, secret, extra_secrets) for item in value]
    if isinstance(value, str):
        from agent.redact import redact_sensitive_text
        for protected in (secret, *extra_secrets):
            variants = (protected, quote(protected, safe=""), base64.b64encode(protected.encode()).decode())
            for variant in variants:
                value = value.replace(variant, "[REDACTED]")
        return redact_sensitive_text(value, force=True)
    return value


def request(handle, service, services, current):
    secret = ""
    extra_secrets = ()
    try:
        if not current():
            raise ValueError("Task ended")
        url, header, scheme = binding(services, service)
        from agent.vault_store import get_vault_store
        from agent.redact import register_vault_redaction_value
        store = get_vault_store()
        meta = store.get_meta(handle)
        if meta is None or meta.kind not in ("api_key", "token") or meta.label != service:
            raise ValueError("Credential does not match service")
        secret = store.resolve_secret(handle)["value"]
        if "\r" in secret or "\n" in secret:
            raise ValueError("Invalid credential")
        register_vault_redaction_value(secret)
        if not current():
            raise ValueError("Task ended")
        if scheme == "cloudflare_access":
            from agent.secret_scope import get_secret
            client_id = get_secret("EXECUTOR_CF_ACCESS_CLIENT_ID")
            if not client_id or "\r" in client_id or "\n" in client_id:
                raise ValueError("Cloudflare Access client ID is unavailable")
            extra_secrets = (client_id,)
            headers = {
                "CF-Access-Client-Id": client_id,
                "CF-Access-Client-Secret": secret,
            }
        else:
            headers = {header: "Bearer " + secret if scheme == "bearer" else secret}
        result = asyncio.run(fetch(url, headers))
        if not current():
            raise ValueError("Task ended")
        return json.dumps(sanitise(result, secret, extra_secrets))
    except Exception:
        return json.dumps({"success": False,
                           "error": "Credential request refused or failed. Check the configured service, handle and active task."})
    finally:
        secret = ""
