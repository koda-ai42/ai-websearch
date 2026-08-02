from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import yaml

SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "key",
    "password",
    "secret",
    "sig",
    "signature",
    "token",
}


@dataclass(frozen=True)
class UrlPolicyResult:
    url: str
    allowed: bool
    reason: str


def _host_matches(host: str, domain: str) -> bool:
    domain = domain.casefold().strip().rstrip(".")
    return bool(domain) and (host == domain or host.endswith("." + domain))


def _blocked_domains(path: Path | None = None) -> list[str]:
    selected = path or Path("config/url_policy.yml")
    if not selected.exists():
        return []
    try:
        payload = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("Could not read config/url_policy.yml") from exc
    values = payload.get("blocked_domains", []) if isinstance(payload, dict) else []
    if not isinstance(values, list):
        raise ValueError("url_policy.yml blocked_domains must contain a list")
    return [str(value).casefold().strip().rstrip(".") for value in values if str(value).strip()]


def check_url(url: str, *, policy_path: Path | None = None) -> UrlPolicyResult:
    try:
        parsed = urlsplit(url.strip())
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not host:
            return UrlPolicyResult(url, False, "only absolute HTTP(S) URLs are allowed")
        if parsed.username is not None or parsed.password is not None:
            return UrlPolicyResult(url, False, "URLs containing credentials are not allowed")
        query_keys = {
            key.casefold() for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        }
        if query_keys & SENSITIVE_QUERY_KEYS:
            return UrlPolicyResult(
                url, False, "URLs containing credential-like query parameters are not allowed"
            )
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
            return UrlPolicyResult(url, False, "local network destinations are not allowed")
        try:
            literal_address = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            literal_address = None
        if literal_address is not None and not literal_address.is_global:
            return UrlPolicyResult(url, False, "non-public network destinations are not allowed")
        if any(_host_matches(host, domain) for domain in _blocked_domains(policy_path)):
            return UrlPolicyResult(url, False, "domain is blocked by local URL policy")
    except ValueError:
        raise
    except Exception:
        return UrlPolicyResult(url, False, "URL could not be parsed")
    return UrlPolicyResult(url, True, "allowed by URL policy")


async def check_url_network(url: str, *, policy_path: Path | None = None) -> UrlPolicyResult:
    """Apply URL policy and verify that DNS resolves only to public addresses."""

    initial = check_url(url, policy_path=policy_path)
    if not initial.allowed:
        return initial
    parsed = urlsplit(url.strip())
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        records = await asyncio.get_running_loop().getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except (OSError, socket.gaierror):
        return UrlPolicyResult(url, False, "destination hostname could not be resolved")
    addresses = {record[4][0] for record in records if record[4]}
    if not addresses:
        return UrlPolicyResult(url, False, "destination hostname did not resolve")
    if any(not ipaddress.ip_address(address).is_global for address in addresses):
        return UrlPolicyResult(url, False, "destination resolved to a non-public network address")
    return initial


def check_urls(urls: list[str]) -> list[dict]:
    return [check_url(url).__dict__ for url in urls]
