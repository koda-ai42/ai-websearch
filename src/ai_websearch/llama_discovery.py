from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import settings
from .errors import (
    LlamaAuthenticationError,
    LlamaServerNotFoundError,
    LlamaVerificationError,
    MultipleLlamaServersError,
    TokenCountError,
)
from .llama_client import DetectedLlamaServer, count_tokens, verify_server


@dataclass(frozen=True)
class ProcessCandidate:
    pid: int
    source: str
    base_url: str


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.llama_cpp_process_inspection_timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def _process_lines(source: str) -> str:
    if source == "local":
        return _run(["ps", "-eo", "pid=,args="])
    if shutil.which("distrobox-host-exec"):
        return _run(["distrobox-host-exec", "ps", "-eo", "pid=,args="])
    return ""


def _relevant_environment(pid: int, source: str) -> dict[str, str]:
    wanted = {"LLAMA_ARG_HOST", "LLAMA_ARG_PORT", "LLAMA_ARG_API_PREFIX"}
    try:
        if source == "local":
            raw = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
            entries = [item.decode("utf-8", errors="ignore") for item in raw if item]
        else:
            command = (
                f"tr '\\0' '\\n' < /proc/{int(pid)}/environ 2>/dev/null "
                "| grep -E '^(LLAMA_ARG_HOST|LLAMA_ARG_PORT|LLAMA_ARG_API_PREFIX)=' || true"
            )
            entries = _run(["distrobox-host-exec", "sh", "-lc", command]).splitlines()
    except (OSError, subprocess.SubprocessError):
        return {}
    output: dict[str, str] = {}
    for entry in entries:
        key, sep, value = entry.partition("=")
        if sep and key in wanted:
            output[key] = value
    return output


def _value_after(tokens: list[str], flag: str) -> str | None:
    for index, token in enumerate(tokens):
        if token == flag and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith(flag + "="):
            return token.split("=", 1)[1]
    return None


def _normalize_host(host: str) -> str:
    value = host.strip()
    if value == "0.0.0.0":
        return "127.0.0.1"
    if value == "::":
        return "::1"
    return value or "127.0.0.1"


def _format_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _base_url(tokens: list[str], env: dict[str, str]) -> str:
    host = _normalize_host(_value_after(tokens, "--host") or env.get("LLAMA_ARG_HOST", "127.0.0.1"))
    port_text = _value_after(tokens, "--port") or env.get("LLAMA_ARG_PORT", "8080")
    try:
        port = int(port_text)
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError as exc:
        raise LlamaVerificationError(
            "A detected llama-server process has an invalid port.", details={"port": port_text}
        ) from exc
    prefix = _value_after(tokens, "--api-prefix") or env.get("LLAMA_ARG_API_PREFIX", "")
    prefix = prefix.strip()
    if prefix and not prefix.startswith("/"):
        prefix = "/" + prefix
    prefix = prefix.rstrip("/")
    return f"http://{_format_host(host)}:{port}{prefix}"


def parse_process_output(text: str, source: str) -> list[tuple[int, list[str]]]:
    output: list[tuple[int, list[str]]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_text, sep, command = line.partition(" ")
        if not sep or not pid_text.isdigit():
            continue
        try:
            tokens = shlex.split(command)
        except ValueError:
            continue
        server_index = next(
            (i for i, token in enumerate(tokens) if os.path.basename(token) == "llama-server"), None
        )
        if server_index is None:
            continue
        output.append((int(pid_text), tokens[server_index:]))
    return output


def discover_process_candidates() -> tuple[list[ProcessCandidate], list[str]]:
    candidates: dict[str, ProcessCandidate] = {}
    inspected: list[str] = []
    for source in ("local", "host"):
        text = _process_lines(source)
        if source == "local" or text:
            inspected.append(
                "current process namespace"
                if source == "local"
                else "host process namespace through distrobox-host-exec"
            )
        for pid, tokens in parse_process_output(text, source):
            env = _relevant_environment(pid, source)
            base_url = _base_url(tokens, env)
            candidates.setdefault(base_url, ProcessCandidate(pid, source, base_url))
    return list(candidates.values()), inspected


class LlamaRuntime:
    def __init__(self, redetect_on_token_failure: bool = False) -> None:
        self._server: DetectedLlamaServer | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()
        self.redetect_on_token_failure = redetect_on_token_failure

    async def get(self, force: bool = False) -> DetectedLlamaServer:
        now = time.monotonic()
        if not force and self._server is not None and now < self._expires_at:
            return self._server
        async with self._lock:
            now = time.monotonic()
            if not force and self._server is not None and now < self._expires_at:
                return self._server
            server = await self._detect()
            self._server = server
            self._expires_at = now + max(0, settings.llama_cpp_detection_cache_seconds)
            return server

    async def _detect(self) -> DetectedLlamaServer:
        if settings.llama_cpp_detection_mode == "manual":
            if not settings.llama_cpp_base_url.strip():
                raise LlamaVerificationError(
                    "AI_WEBSEARCH_LLAMA_CPP_BASE_URL is required in manual mode.",
                    resolution="Set AI_WEBSEARCH_LLAMA_CPP_BASE_URL to the selected llama.cpp server.",
                )
            return await verify_server(settings.llama_cpp_base_url, "manual")

        candidates, inspected = discover_process_candidates()
        verified: list[DetectedLlamaServer] = []
        failures: list[dict] = []
        authentication_failures: list[LlamaAuthenticationError] = []
        for candidate in candidates:
            try:
                verified.append(await verify_server(candidate.base_url, "auto"))
            except LlamaAuthenticationError as exc:
                authentication_failures.append(exc)
                failures.append({"base_url": candidate.base_url, "reason": exc.message})
            except Exception as exc:
                failures.append({"base_url": candidate.base_url, "reason": type(exc).__name__})
        deduped = {server.base_url: server for server in verified}
        verified = list(deduped.values())
        if not verified and authentication_failures:
            raise LlamaAuthenticationError(
                "A detected llama.cpp server requires valid authentication.",
                details={"candidates": [failure["base_url"] for failure in failures]},
                resolution="Set AI_WEBSEARCH_LLAMA_CPP_API_KEY.",
            )
        if not verified:
            raise LlamaServerNotFoundError(
                "No verified llama.cpp server was detected.",
                details={
                    "inspected": inspected,
                    "process_candidates": [c.base_url for c in candidates],
                    "verification_failures": failures,
                },
                resolution=[
                    "Start llama-server before starting the MCP server.",
                    "Confirm the process is visible in the current process namespace.",
                    "If using optional Distrobox isolation, confirm distrobox-host-exec can see the host process.",
                    "Use manual mode when llama-server is remote, proxied or in another network namespace.",
                ],
            )
        if len(verified) > 1:
            raise MultipleLlamaServersError(
                "Multiple verified llama.cpp servers were detected.",
                details={
                    "candidates": [
                        server.metadata()
                        for server in sorted(verified, key=lambda item: item.base_url)
                    ]
                },
                resolution={
                    "AI_WEBSEARCH_LLAMA_CPP_DETECTION_MODE": "manual",
                    "AI_WEBSEARCH_LLAMA_CPP_BASE_URL": "Choose one candidate URL",
                },
            )
        return verified[0]

    async def initialize(self) -> DetectedLlamaServer:
        server = await self.get(force=True)
        await count_tokens(server, "startup validation")
        return server

    async def count(self, text: str) -> int:
        server = await self.get()
        try:
            return await count_tokens(server, text)
        except TokenCountError:
            if not self.redetect_on_token_failure:
                raise
            server = await self.get(force=True)
            return await count_tokens(server, text)


runtime = LlamaRuntime(redetect_on_token_failure=False)
