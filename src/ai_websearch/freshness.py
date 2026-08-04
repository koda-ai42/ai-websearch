from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


def _parse_numeric_date(text: str) -> datetime | None:
    """Parse international numeric date formats.

    Supports:
      YYYY[-/.]M[-/.]D   e.g. 2024-1-5, 2024/01/15, 2024.1.5
      D[-/.]M[-/.]YYYY   e.g. 15/1/2024, 5.1.2024, 1/5/2024
      YYYY                e.g. 2024

    For D/M/YYYY ambiguous cases (both components <= 12), defaults to DD/MM/YYYY.
    """
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                return None
        return None

    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", text)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12:
            day, month = a, b
        elif b > 12:
            month, day = a, b
        else:
            day, month = a, b
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                return None
        return None

    m = re.fullmatch(r"(\d{4})", text)
    if m:
        year = int(m.group(1))
        if 1 <= year <= 9999:
            return datetime(year, 1, 1, tzinfo=timezone.utc)
        return None

    return None


def parse_publication_date(value: str | None) -> datetime | None:
    """Parse a publication date string into a UTC datetime.

    Attempts formats in order:
      1. ISO 8601        e.g. 2024-01-15, 2024-01-15T10:30Z
      2. RFC 2822        e.g. Tue, 15 Jan 2024 10:30:00 +0000
      3. YYYY[-/.]M[-/.]D e.g. 2024-1-5, 2024/01/15
      4. D[-/.]M[-/.]YYYY  e.g. 15/1/2024, 1/5/2024 (DD/MM/YYYY for ambiguous)
      5. YYYY (year only)   e.g. 2024
    """
    if not value or not value.strip():
        return None
    text = value.strip()

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            parsed = _parse_numeric_date(text)
            if parsed is None:
                return None
    else:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_publication_date(
    value: str | None,
    fetched_at: str | None,
) -> str | None:
    published = parse_publication_date(value)
    if published is None:
        return None
    fetched = parse_publication_date(fetched_at) or datetime.now(timezone.utc)
    if published > fetched + timedelta(days=1):
        return None
    return published.isoformat()


def freshness_score(
    published_at: str | None,
    *,
    freshness: str | None,
    now: datetime | None = None,
) -> float | None:
    """Compute a recency score for a chunk based on its publication date.

    Returns None when freshness is not explicitly requested.
    Returns 0.5 when publication date is unavailable or clearly future.
    Otherwise applies exponential decay with half-life determined by freshness mode.
    """
    if freshness not in {"day", "month", "year"}:
        return None
    published = parse_publication_date(published_at)
    if published is None:
        return 0.5
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_days = (reference - published).total_seconds() / 86_400
    if age_days < -1:
        return 0.5
    half_life = {"day": 2.0, "month": 30.0, "year": 180.0}.get(freshness, 90.0)
    return max(0.0, min(1.0, math.exp(-max(0.0, age_days) * math.log(2.0) / half_life)))
