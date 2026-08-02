from __future__ import annotations

import ipaddress
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .config import settings
from .errors import LlamaAuthenticationError, LlamaVerificationError, TokenCountError

_scoped_client: ContextVar[httpx.AsyncClient | None] = ContextVar(
    "ai_websearch_llama_client",
    default=None,
)


@asynccontextmanager
async def llama_client_scope():
    existing = _scoped_client.get()
    if existing is not None:
        yield existing
        return
    async with httpx.AsyncClient(
        timeout=settings.llama_cpp_request_timeout_seconds,
        follow_redirects=False,
    ) as client:
        token = _scoped_client.set(client)
        try:
            yield client
        finally:
            _scoped_client.reset(token)


@dataclass(frozen=True)
class DetectedLlamaServer:
    base_url: str
    context_tokens: int
    detection_mode: str

    def metadata(self) -> dict:
        return {
            "detection_mode": self.detection_mode,
            "base_url": self.base_url,
            "context_tokens": self.context_tokens,
        }


def _headers() -> dict[str, str]:
    return (
        {"Authorization": f"Bearer {settings.llama_cpp_api_key}"}
        if settings.llama_cpp_api_key
        else {}
    )


def _model_params() -> dict[str, str]:
    return {"model": settings.llama_cpp_model} if settings.llama_cpp_model else {}


def validate_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise LlamaVerificationError(
            "AI_WEBSEARCH_LLAMA_CPP_BASE_URL must be an absolute HTTP or HTTPS URL.",
            details={"base_url": value},
        )
    if settings.llama_cpp_local_only:
        host = parsed.hostname.lower()
        is_local = host == "localhost"
        if not is_local:
            try:
                is_local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_local = False
        if not is_local:
            raise LlamaVerificationError(
                "AI_WEBSEARCH_LLAMA_CPP_LOCAL_ONLY=true rejects a non-loopback llama.cpp endpoint.",
                details={"base_url": value},
                resolution="Use a loopback URL or explicitly set AI_WEBSEARCH_LLAMA_CPP_LOCAL_ONLY=false.",
            )
    return value


async def verify_server(base_url: str, detection_mode: str) -> DetectedLlamaServer:
    base_url = validate_base_url(base_url)
    try:
        async with httpx.AsyncClient(
            timeout=settings.llama_cpp_request_timeout_seconds, follow_redirects=False
        ) as client:
            response = await client.get(
                base_url + "/props", headers=_headers(), params=_model_params()
            )
    except Exception as exc:
        raise LlamaVerificationError(
            "The llama.cpp /props endpoint was unreachable.",
            details={"base_url": base_url, "reason": type(exc).__name__},
        ) from exc
    if response.status_code == 401:
        raise LlamaAuthenticationError(
            "The detected llama.cpp server requires valid authentication.",
            details={"base_url": base_url},
            resolution="Set AI_WEBSEARCH_LLAMA_CPP_API_KEY.",
        )
    try:
        response.raise_for_status()
        payload = response.json()
        n_ctx = payload["default_generation_settings"]["n_ctx"]
        n_ctx = int(n_ctx)
        if n_ctx < 1024:
            raise ValueError(f"invalid n_ctx {n_ctx}")
    except Exception as exc:
        raise LlamaVerificationError(
            "The llama.cpp /props response did not contain a valid default_generation_settings.n_ctx value.",
            details={
                "base_url": base_url,
                "status": response.status_code,
                "reason": type(exc).__name__,
            },
        ) from exc
    return DetectedLlamaServer(base_url, n_ctx, detection_mode)


async def count_tokens(server: DetectedLlamaServer, text: str) -> int:
    if _scoped_client.get() is None:
        async with llama_client_scope():
            return await count_tokens(server, text)
    payload: dict = {"content": text, "add_special": False}
    if settings.llama_cpp_model:
        payload["model"] = settings.llama_cpp_model
    try:
        client = _scoped_client.get()
        if client is None:  # pragma: no cover - established by the wrapper above
            raise RuntimeError("llama.cpp client scope was not initialized")
        try:
            response = await client.post(
                server.base_url + "/tokenize",
                headers=_headers(),
                json=payload,
            )
        finally:
            client.cookies.clear()
    except Exception as exc:
        raise TokenCountError(
            "The detected llama.cpp server could not tokenize the packed MCP response.",
            details={"base_url": server.base_url, "reason": type(exc).__name__},
            resolution="Check /tokenize, authentication, API prefix, model routing and server availability.",
        ) from exc
    if response.status_code == 401:
        raise LlamaAuthenticationError(
            "The detected llama.cpp server requires valid authentication.",
            details={"base_url": server.base_url},
            resolution="Set AI_WEBSEARCH_LLAMA_CPP_API_KEY.",
        )
    try:
        response.raise_for_status()
        tokens = response.json()["tokens"]
        if not isinstance(tokens, list):
            raise ValueError("tokens is not a list")
        return len(tokens)
    except Exception as exc:
        raise TokenCountError(
            "The detected llama.cpp server returned an invalid /tokenize response.",
            details={
                "base_url": server.base_url,
                "status": response.status_code,
                "reason": type(exc).__name__,
            },
            resolution="Check /tokenize, API prefix and router model selection.",
        ) from exc
