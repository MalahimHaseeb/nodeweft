import asyncio
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.engine.errors import NodeError
from app.nodes.util import HEADER_NAME

MAX_RESPONSE_BYTES = 1_000_000
BLOCKED_HEADERS = {"host", "content-length", "transfer-encoding", "connection"}


def is_blocked_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def assert_public_destination(url: str, allowed_hosts: list[str]) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise NodeError("URL must start with http:// or https://")
    host = parts.hostname.lower()
    if allowed_hosts and host not in allowed_hosts:
        raise NodeError("This host is not on the allowed hosts list")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        resolved = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise NodeError("Could not resolve the host name") from None
    if not resolved or any(is_blocked_address(entry[4][0]) for entry in resolved):
        raise NodeError("Requests to private or internal addresses are blocked")


def clean_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    if not isinstance(headers, dict):
        raise NodeError("Headers must be an object")
    cleaned: dict[str, str] = {}
    for name, value in headers.items():
        if not HEADER_NAME.match(str(name)) or str(name).lower() in BLOCKED_HEADERS:
            raise NodeError(f"Header '{name}' is not allowed")
        text = str(value)
        if "\r" in text or "\n" in text:
            raise NodeError(f"Header '{name}' contains a line break")
        cleaned[str(name)] = text
    return cleaned


async def safe_request(
    method: str,
    url: str,
    headers: Any,
    body: Any,
    timeout_seconds: int,
    allowed_hosts: list[str],
) -> dict:
    url = str(url).strip()
    await assert_public_destination(url, allowed_hosts)
    request_kwargs: dict[str, Any] = {"headers": clean_headers(headers)}
    if body is not None and method in ("POST", "PUT", "PATCH", "DELETE"):
        if isinstance(body, (dict, list)):
            request_kwargs["json"] = body
        else:
            request_kwargs["content"] = str(body).encode()

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout_seconds) as client:
            async with client.stream(method, url, **request_kwargs) as response:
                received = bytearray()
                async for chunk in response.aiter_bytes():
                    received.extend(chunk)
                    if len(received) > MAX_RESPONSE_BYTES:
                        raise NodeError("Response is larger than 1 MB")
                content_type = response.headers.get("content-type", "")
                status_code = response.status_code
    except httpx.TimeoutException:
        raise NodeError("The request timed out") from None
    except httpx.HTTPError:
        raise NodeError("The request failed") from None

    text = received.decode("utf-8", errors="replace")
    parsed: Any = text[:10000]
    if "json" in content_type:
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = text[:10000]
    return {"status_code": status_code, "body": parsed}
