from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

TEMPORAL_TERMS = {
    "current",
    "currently",
    "latest",
    "newest",
    "recent",
    "recently",
    "today",
    "tonight",
    "now",
    "updated",
    "this year",
    "this month",
}

DAY_TERMS = {"today", "tonight", "now", "past 24 hours", "last 24 hours"}
MONTH_TERMS = {"this month", "past month", "last month", "recent", "recently"}


def parse_publication_date(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
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


def freshness_window(query: str, freshness: str | None) -> str | None:
    if freshness in {"day", "month", "year"}:
        return freshness
    if freshness != "auto":
        return None
    lowered = " ".join(query.casefold().split())
    if any(term in lowered for term in DAY_TERMS):
        return "day"
    if any(term in lowered for term in MONTH_TERMS):
        return "month"
    return "year" if query_needs_freshness(query, freshness) else None


def query_needs_freshness(query: str, freshness: str | None) -> bool:
    if freshness in {"day", "month", "year"}:
        return True
    lowered = " ".join(query.casefold().split())
    if any(term in lowered for term in TEMPORAL_TERMS):
        return True
    years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", lowered)]
    current_year = datetime.now(timezone.utc).year
    return bool(years and max(years) >= current_year)


def freshness_score(
    published_at: str | None,
    *,
    query: str,
    freshness: str | None,
    now: datetime | None = None,
) -> float | None:
    if not query_needs_freshness(query, freshness):
        return None
    published = parse_publication_date(published_at)
    if published is None:
        return 0.5
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_days = (reference - published).total_seconds() / 86_400
    if age_days < -1:
        return 0.5
    half_life = {"day": 2.0, "month": 30.0, "year": 180.0}.get(freshness or "", 90.0)
    return max(0.0, min(1.0, math.exp(-max(0.0, age_days) * math.log(2.0) / half_life)))
