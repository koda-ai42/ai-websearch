from __future__ import annotations

from dataclasses import dataclass

from .config import settings
from .errors import ContextBudgetError


@dataclass(frozen=True)
class ContextBudget:
    model_context_tokens: int
    available_after_reservations: int
    ratio_cap: int
    maximum_web_tokens: int
    requested_web_tokens: int | None
    applied_web_tokens: int
    warnings: tuple[str, ...] = ()

    def metadata(self, packed_result_tokens: int = 0) -> dict:
        return {
            "maximum_web_tokens": self.maximum_web_tokens,
            "requested_web_tokens": self.requested_web_tokens,
            "applied_web_tokens": self.applied_web_tokens,
            "packed_result_tokens": packed_result_tokens,
            "max_web_context_ratio": settings.max_web_context_ratio,
            "reservations": {
                "output": settings.reserved_output_tokens,
                "system_tools": settings.reserved_system_tool_tokens,
                "history": settings.reserved_history_tokens,
                "safety_margin": settings.context_safety_margin_tokens,
            },
        }


def calculate_context_budget(n_ctx: int, requested_tokens: int | None = None) -> ContextBudget:
    if n_ctx < 1:
        raise ContextBudgetError(
            "llama.cpp reported an invalid model context size.", details={"n_ctx": n_ctx}
        )
    available = n_ctx - settings.reserved_non_web_tokens
    ratio_cap = int(n_ctx * settings.max_web_context_ratio)
    maximum = min(available, ratio_cap)
    if maximum < 1000:
        raise ContextBudgetError(
            "Insufficient context remains for web evidence.",
            details={
                "model_context_tokens": n_ctx,
                "reserved_tokens": settings.reserved_non_web_tokens,
                "available_after_reservations": available,
                "ratio_cap": ratio_cap,
            },
            resolution="Reduce reservation settings or use a model with a larger context window.",
        )
    warnings: list[str] = []
    if requested_tokens is None:
        applied = maximum
    else:
        if requested_tokens < 1:
            raise ContextBudgetError("context_budget_tokens must be at least 1")
        applied = min(requested_tokens, maximum)
        if requested_tokens > maximum:
            warnings.append(
                f"Requested context budget {requested_tokens} was clamped to {maximum} tokens."
            )
    return ContextBudget(
        n_ctx, available, ratio_cap, maximum, requested_tokens, applied, tuple(warnings)
    )
