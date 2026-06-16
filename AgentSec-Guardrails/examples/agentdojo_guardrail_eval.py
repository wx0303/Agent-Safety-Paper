from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_guardrail.runtime import (  # noqa: E402
    agentdojo_eval_to_dict,
    build_agentdojo_smoke_cases,
    format_agentdojo_summary,
    load_agentdojo_path,
    load_agentdojo_jsonl,
    run_agentdojo_cases,
    validate_expected_results,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run AgentDojo-shaped benchmark cases through AgentSec Guardrails."
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Optional AgentDojo JSON, JSONL, or runs directory to replay instead of built-in smoke cases.",
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        help="Deprecated alias for --input when the source is JSONL.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a Markdown table.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail with a non-zero exit code when built-in expected outcomes are not met.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.input:
        cases = load_agentdojo_path(args.input)
    elif args.jsonl:
        cases = load_agentdojo_jsonl(args.jsonl)
    else:
        cases = build_agentdojo_smoke_cases()
    results = run_agentdojo_cases(cases)

    if args.json:
        print(json.dumps([agentdojo_eval_to_dict(result) for result in results], indent=2, ensure_ascii=False))
    else:
        print(format_agentdojo_summary(results))

    failures = validate_expected_results(results)
    if failures:
        print("\nExpected outcome failures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
