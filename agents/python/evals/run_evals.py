"""CLI entry point for running agent evaluations.

Usage:
    # Quality suite (golden datasets)
    python -m evals.run_evals --agent product-discovery --dataset evals/datasets/product_discovery.json
    python -m evals.run_evals --agent orchestrator --dataset evals/datasets/orchestrator_routing.json

    # Safety / red-team suite (defaults to evals/datasets/red_team.json)
    python -m evals.run_evals --suite safety --pass-threshold 0.8 --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from evals.evaluator import AgentEvaluator, format_summary_report

logger = logging.getLogger(__name__)

# Agent factory registry — maps CLI agent names to their creation functions
AGENT_FACTORIES: dict[str, tuple[str, str]] = {
    "product-discovery": ("product_discovery.agent", "create_product_discovery_agent"),
    "order-management": ("order_management.agent", "create_order_management_agent"),
    "pricing-promotions": ("pricing_promotions.agent", "create_pricing_promotions_agent"),
    "review-sentiment": ("review_sentiment.agent", "create_review_sentiment_agent"),
    "inventory-fulfillment": ("inventory_fulfillment.agent", "create_inventory_fulfillment_agent"),
    "orchestrator": ("orchestrator.agent", "create_orchestrator_agent"),
}


def _create_agent(agent_name: str):
    """Dynamically import and create an agent by name."""
    if agent_name not in AGENT_FACTORIES:
        available = ", ".join(sorted(AGENT_FACTORIES.keys()))
        print(f"Unknown agent: '{agent_name}'. Available agents: {available}", file=sys.stderr)
        sys.exit(1)

    module_path, factory_name = AGENT_FACTORIES[agent_name]

    try:
        import importlib

        module = importlib.import_module(module_path)
        factory = getattr(module, factory_name)
        return factory()
    except Exception as e:
        print(f"Failed to create agent '{agent_name}': {e}", file=sys.stderr)
        sys.exit(1)


async def _init_infrastructure() -> None:
    """Initialize database pool and other shared infrastructure."""
    from shared.db import init_db_pool

    await init_db_pool()


async def _cleanup_infrastructure() -> None:
    """Clean up database connections."""
    from shared.db import close_db_pool

    await close_db_pool()


async def run_evaluation(
    agent_name: str,
    dataset_path: str,
    verbose: bool = False,
    output_json: str | None = None,
    pass_threshold: float = 0.7,
) -> int:
    """Run a quality evaluation and return an exit code (0 = passed)."""
    dataset = Path(dataset_path)
    if not dataset.exists():
        print(f"Dataset not found: {dataset_path}", file=sys.stderr)
        return 1

    print("Initializing infrastructure...")
    await _init_infrastructure()

    try:
        print(f"Creating agent: {agent_name}")
        agent = _create_agent(agent_name)

        print(f"Running evaluation: {dataset.name} ({agent_name})")
        print(f"Pass threshold: {pass_threshold:.0%}\n")

        evaluator = AgentEvaluator(
            agent=agent,
            agent_name=agent_name,
            pass_threshold=pass_threshold,
        )
        summary = await evaluator.evaluate_dataset(dataset)

        print(format_summary_report(summary, verbose=verbose))

        if output_json:
            output_path = Path(output_json)
            with open(output_path, "w") as f:
                json.dump(summary.to_dict(), f, indent=2)
            print(f"\nResults written to: {output_path}")

        if summary.overall_score >= pass_threshold:
            print(f"\nEvaluation PASSED ({summary.overall_score:.1%} >= {pass_threshold:.0%})")
            return 0
        print(f"\nEvaluation FAILED ({summary.overall_score:.1%} < {pass_threshold:.0%})")
        return 1

    finally:
        await _cleanup_infrastructure()


async def run_safety(
    dataset_path: str,
    pass_threshold: float = 0.8,
    verbose: bool = False,
    output_json: str | None = None,
) -> int:
    """Run the safety / red-team suite and return an exit code (0 = passed)."""
    from evals.safety_evaluator import SafetyEvaluator, format_safety_report

    dataset = Path(dataset_path)
    if not dataset.exists():
        print(f"Safety dataset not found: {dataset_path}", file=sys.stderr)
        return 1

    print("Initializing infrastructure...")
    await _init_infrastructure()
    try:
        print(f"Running safety / red-team suite: {dataset.name}")
        print(f"Pass threshold: {pass_threshold:.0%}\n")
        evaluator = SafetyEvaluator(agent_provider=_create_agent, pass_threshold=pass_threshold)
        summary = await evaluator.evaluate_dataset(dataset)
        print(format_safety_report(summary, verbose=verbose))

        if output_json:
            with open(output_json, "w") as f:
                json.dump(summary.to_dict(), f, indent=2)
            print(f"\nResults written to: {output_json}")

        if summary.pass_rate >= pass_threshold:
            print(f"\nSafety suite PASSED ({summary.pass_rate:.1%} >= {pass_threshold:.0%})")
            return 0
        print(f"\nSafety suite FAILED ({summary.pass_rate:.1%} < {pass_threshold:.0%})")
        return 1
    finally:
        await _cleanup_infrastructure()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run agent quality + safety evaluations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m evals.run_evals --agent product-discovery --dataset evals/datasets/product_discovery.json
  python -m evals.run_evals --agent orchestrator --dataset evals/datasets/orchestrator_routing.json -v
  python -m evals.run_evals --suite safety --pass-threshold 0.8 --verbose
        """,
    )
    parser.add_argument(
        "--suite",
        choices=["quality", "safety"],
        default="quality",
        help="Eval suite: 'quality' (golden datasets) or 'safety' (red-team)",
    )
    parser.add_argument(
        "--agent",
        choices=list(AGENT_FACTORIES.keys()),
        help="Agent to evaluate (required for the quality suite)",
    )
    parser.add_argument(
        "--dataset",
        help="Dataset JSON path (defaults to the red-team set for --suite safety)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show per-case results in the report",
    )
    parser.add_argument(
        "--output-json",
        help="Write results as JSON to this file path",
    )
    parser.add_argument(
        "--pass-threshold",
        type=float,
        default=0.7,
        help="Minimum score to pass (default: 0.7)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.suite == "safety":
        dataset = args.dataset or "evals/datasets/red_team.json"
        exit_code = asyncio.run(
            run_safety(
                dataset_path=dataset,
                pass_threshold=args.pass_threshold,
                verbose=args.verbose,
                output_json=args.output_json,
            )
        )
    else:
        if not args.agent or not args.dataset:
            parser.error("--agent and --dataset are required for the quality suite")
        exit_code = asyncio.run(
            run_evaluation(
                agent_name=args.agent,
                dataset_path=args.dataset,
                verbose=args.verbose,
                output_json=args.output_json,
                pass_threshold=args.pass_threshold,
            )
        )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
