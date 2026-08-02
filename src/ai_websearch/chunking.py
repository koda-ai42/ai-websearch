from __future__ import annotations

import re

from .clean import clean_markdown
from .config import settings

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|\*\*[^*]+\*\*\s*:)")


def _structured_block(block: str) -> bool:
    return any(_HEADING.match(line) or _LIST_ITEM.match(line) for line in block.splitlines())


def _semantic_blocks(text: str) -> list[str]:
    """Split paragraphs and top-level Markdown sections without losing headings."""

    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append("\n".join(current).strip())
        current = []

    for line in text.splitlines():
        stripped = line.strip()
        starts_section = bool(re.match(r"^\s{0,3}#{1,2}\s+", stripped))
        if starts_section and current:
            flush()
        if not stripped:
            flush()
            continue
        current.append(stripped)
    flush()
    return blocks


def _boundary_cut(text: str, limit: int) -> int:
    """Return a non-zero split at a line, sentence, or word boundary."""

    if len(text) <= limit:
        return len(text)
    window = text[: limit + 1]
    minimum = max(1, limit // 2)
    newline = window.rfind("\n", minimum)
    if newline >= minimum:
        return newline + 1
    sentence_ends = [
        match.end() for match in re.finditer(r"[.!?](?:\s+|$)", window) if match.end() >= minimum
    ]
    if sentence_ends:
        return sentence_ends[-1]
    whitespace = [match.end() for match in re.finditer(r"\s+", window) if match.end() >= minimum]
    return whitespace[-1] if whitespace else limit


def _split_long_line(line: str, limit: int) -> list[str]:
    remaining = line.strip()
    pieces: list[str] = []
    while len(remaining) > limit:
        cut = _boundary_cut(remaining, limit)
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _split_block(block: str, chunk_size: int) -> list[str]:
    if len(block) <= chunk_size:
        return [block]
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return []
    heading = lines[0] if _HEADING.match(lines[0]) else ""
    output: list[str] = []
    if heading and len(heading) + 2 >= chunk_size:
        output.extend(_split_long_line(heading, chunk_size))
        heading = ""
    current = heading
    body_lines = lines[1:] if heading else lines

    def flush() -> None:
        nonlocal current
        if current.strip():
            output.append(current.strip())
        current = heading

    for line in body_lines:
        prefix_size = len(heading) + 1 if heading else 0
        line_limit = max(1, chunk_size - prefix_size)
        for fragment in _split_long_line(line, line_limit):
            candidate = f"{current}\n{fragment}" if current else fragment
            if len(candidate) <= chunk_size:
                current = candidate
                continue
            flush()
            current = f"{heading}\n{fragment}" if heading else fragment
    flush()
    return output


def _safe_overlap_tail(text: str, overlap: int) -> str:
    if overlap <= 0 or not text:
        return ""
    start = max(0, len(text) - overlap)
    if start == 0:
        return text.strip()
    suffix = text[start:]
    boundary = re.search(r"(?:\n+|(?<=[.!?])\s+|\s+)", suffix)
    if boundary is None:
        return ""
    return suffix[boundary.end() :].strip()


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
    min_chunk_chars: int | None = None,
) -> list[str]:
    chunk_size = chunk_size or settings.chunk_size_chars
    overlap = overlap if overlap is not None else settings.chunk_overlap_chars
    min_chunk_chars = min_chunk_chars or settings.min_chunk_chars

    text = clean_markdown(text)
    if not text:
        return []

    blocks = _semantic_blocks(text)
    pieces = [
        (piece, _structured_block(block))
        for block in blocks
        for piece in _split_block(block, chunk_size)
    ]
    chunks: list[str] = []
    current = ""
    current_structured = False

    def flush() -> None:
        nonlocal current, current_structured
        if len(current.strip()) >= min_chunk_chars:
            chunks.append(current.strip())
        current = ""
        current_structured = False

    for piece, structured in pieces:
        piece = piece.strip()
        if not piece:
            continue
        starts_section = bool(re.match(r"^\s{0,3}#{1,2}\s+", piece))
        if not current:
            current = piece
            current_structured = structured
        elif starts_section:
            flush()
            current = piece
            current_structured = structured
        elif len(current) + len(piece) + 2 <= chunk_size:
            current = f"{current}\n\n{piece}"
            current_structured = current_structured or structured
        else:
            previous = current
            previous_structured = current_structured
            flush()
            available_overlap = max(0, chunk_size - len(piece) - 2)
            tail = (
                ""
                if structured or previous_structured
                else _safe_overlap_tail(previous, min(overlap, available_overlap))
            )
            current = f"{tail}\n\n{piece}" if tail else piece
            current_structured = structured

    flush()
    return chunks
