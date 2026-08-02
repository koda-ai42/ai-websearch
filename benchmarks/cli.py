from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .canonical_urls import run_canonical_url_benchmark
from .crawl_responses import run_crawl_response_benchmark
from .evidence_representation import run_evidence_representation_benchmark
from .final_evidence import run_final_evidence_benchmark
from .freshness_metadata import run_freshness_metadata_benchmark
from .isolation import isolated_environment
from .production_cache import run_production_cache_benchmark
from .production_retrieval import run_production_retrieval_benchmark
from .replay import run_offline_benchmark
from .request_deadlines import run_request_deadline_benchmark
from .research_limits import run_research_limits_benchmark
from .search_failures import run_search_failure_benchmark
from .security_surface import run_security_surface_benchmark
from .stage2 import run_stage2_benchmark
from .stage3 import run_stage3_benchmark
from .stage4 import run_stage4_benchmark
from .stage5 import run_stage5_benchmark
from .stage6 import run_stage6_benchmark
from .stage7 import run_stage7_benchmark
from .stage8 import run_stage8_benchmark
from .stage9 import run_stage9_benchmark
from .stage12 import run_stage12_benchmark
from .temporal_schedule import run_temporal_schedule_benchmark

LIVE_ENV_GUARD = "AI_WEBSEARCH_BENCHMARK_ALLOW_LIVE"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ai-websearch evaluation harness")
    parser.add_argument("--corpus", type=Path, help="versioned offline corpus JSON")
    parser.add_argument("--output", type=Path, help="write JSON to this explicit artifact path")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--stage",
        choices=(
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "10",
            "11",
            "12",
            "13",
            "14",
            "15",
            "16",
            "17",
            "18",
            "19",
            "20",
            "21",
            "22",
        ),
        default="1",
        help="offline benchmark stage",
    )
    selection.add_argument(
        "--all",
        action="store_true",
        help="run every offline benchmark stage with its checked-in corpus",
    )
    parser.add_argument(
        "--live", action="store_true", help="request live integrations (never implied)"
    )
    parser.add_argument(
        "--allow-live", action="store_true", help="acknowledge live network/browser execution"
    )
    return parser


def _validate_live_opt_in(args: argparse.Namespace) -> None:
    if not args.live:
        return
    if not args.allow_live or os.environ.get(LIVE_ENV_GUARD) != "1":
        raise SystemExit(
            f"Live benchmarks require both --allow-live and {LIVE_ENV_GUARD}=1. "
            "Offline replay remains the default."
        )
    raise SystemExit(
        "Live integration execution is intentionally not automated by the benchmark harness. "
        "The explicit opt-in was accepted; follow docs/BENCHMARKING.md for the manual live matrix."
    )


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    _validate_live_opt_in(args)
    with isolated_environment():
        runners = {
            "1": run_offline_benchmark,
            "2": run_stage2_benchmark,
            "3": run_stage3_benchmark,
            "4": run_stage4_benchmark,
            "5": run_stage5_benchmark,
            "6": run_stage6_benchmark,
            "7": run_stage7_benchmark,
            "8": run_stage8_benchmark,
            "9": run_stage9_benchmark,
            "10": lambda _path=None: run_production_retrieval_benchmark(include_timing=True),
            "11": run_research_limits_benchmark,
            "12": run_stage12_benchmark,
            "13": run_production_cache_benchmark,
            "14": run_evidence_representation_benchmark,
            "15": run_final_evidence_benchmark,
            "16": run_search_failure_benchmark,
            "17": run_crawl_response_benchmark,
            "18": run_canonical_url_benchmark,
            "19": run_freshness_metadata_benchmark,
            "20": run_security_surface_benchmark,
            "21": run_request_deadline_benchmark,
            "22": run_temporal_schedule_benchmark,
        }
        if args.all:
            if args.corpus:
                raise SystemExit("--corpus can be used only with one --stage")
            result = {stage: runner(None) for stage, runner in runners.items()}
        else:
            result = runners[args.stage](args.corpus)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        destination = args.output.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
