"""
Helix eval runner — uploads datasets to LangSmith and runs agent quality evals.

Each eval:
  1. Ensures a LangSmith dataset exists for the agent (creates it if not).
  2. Upserts the sample examples from evals/datasets.py.
  3. Runs evaluate() — calls the agent prompt with each example and scores
     the output using the evaluators in evals/evaluators.py.
  4. Prints a pass/fail summary and exits non-zero if any eval fails below
     the pass threshold.

Usage:
    python -m evals.run                             # run all evals
    python -m evals.run --agent crash_handler       # run one agent only
    python -m evals.run --dataset-only              # push datasets, skip LLM calls
    python -m evals.run --experiment my-run-v2      # custom experiment name prefix

Environment variables required:
    LANGSMITH_API_KEY     LangSmith API key
    LANGSMITH_PROJECT     LangSmith project name (default: "helix")
    ANTHROPIC_API_KEY     or OPENROUTER_API_KEY — for the LLM calls

Exit codes:
    0   all evals passed (or --dataset-only mode)
    1   one or more evals failed below the pass threshold
    2   LangSmith API key not set
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime

# A single event loop reused across all eval target calls, so httpx can close
# its async transport cleanly instead of hitting "Event loop is closed".
_LOOP = asyncio.new_event_loop()

from langsmith import Client
from langsmith.evaluation import evaluate

from core.config import get_langsmith_config
from agents.crash_handler import prompts as crash_handler_prompts
from agents.dev import prompts as dev_prompts
from agents.qa import prompts as qa_prompts
from core.llm import complete
from evals.datasets import CRASH_HANDLER_EXAMPLES, DEV_EXAMPLES, QA_EXAMPLES
from evals.evaluators import (
    after_block_differs_from_before,
    correct_error_type,
    has_after_block,
    has_before_block,
    has_required_crash_fields,
    has_required_qa_fields,
    has_root_cause_sentence,
    no_new_imports_in_fix,
    test_avoids_exception_assertion,
    test_content_not_empty,
    valid_json_crash_handler,
    valid_json_qa,
    valid_severity,
)

# Minimum average score (across all examples) required to pass an eval suite.
_PASS_THRESHOLD = 0.8


# ---------------------------------------------------------------------------
# Dataset management
# ---------------------------------------------------------------------------

def upsert_dataset(client: Client, name: str, examples: list[dict]) -> str:
    """
    Create the named LangSmith dataset if it does not exist, then upsert
    all examples from the provided list.

    Args:
        client:   Authenticated LangSmith client.
        name:     Dataset name, e.g. "helix-crash-handler".
        examples: List of dicts with "inputs" and "metadata" keys.

    Returns:
        The dataset ID.
    """
    existing = [d for d in client.list_datasets() if d.name == name]
    if existing:
        dataset = existing[0]
        print(f"  Dataset '{name}' already exists (id={dataset.id})")
    else:
        dataset = client.create_dataset(name, description=f"Helix eval dataset for {name}")
        print(f"  Created dataset '{name}' (id={dataset.id})")

    # Upsert examples by metadata label so re-running is idempotent.
    existing_examples = {
        ex.metadata.get("label"): ex
        for ex in client.list_examples(dataset_id=dataset.id)
        if ex.metadata
    }

    created = 0
    for entry in examples:
        label = entry.get("metadata", {}).get("label", "")
        if label and label in existing_examples:
            continue  # already present — skip to keep dataset history clean
        client.create_example(
            inputs=entry["inputs"],
            metadata=entry.get("metadata", {}),
            dataset_id=dataset.id,
        )
        created += 1

    print(f"  Added {created} new example(s) ({len(existing_examples)} already existed)")
    return str(dataset.id)


# ---------------------------------------------------------------------------
# Eval target functions
#
# Each target wraps an agent prompt call. evaluate() calls these synchronously
# (one call per dataset example), so we run async complete() via asyncio.run().
# ---------------------------------------------------------------------------

def crash_handler_target(inputs: dict) -> dict:
    """
    Eval target for the Crash Handler agent.

    Calls the crash_handler LLM prompt with the given inputs and returns the
    raw response string so evaluators can parse and score it.

    Args:
        inputs: Keys matching crash_handler_prompts.user() parameters.

    Returns:
        {"output": raw LLM response string}
    """
    prompt = crash_handler_prompts.user(**inputs)
    response = _LOOP.run_until_complete(
        complete("crash_handler", prompt, system=crash_handler_prompts.SYSTEM)
    )
    return {"output": response}


def qa_target(inputs: dict) -> dict:
    """
    Eval target for the QA agent.

    Calls the QA LLM prompt with the given inputs and returns the raw response
    string so evaluators can parse and score it.

    Args:
        inputs: Keys matching qa_prompts.user() parameters.

    Returns:
        {"output": raw LLM response string}
    """
    prompt = qa_prompts.user(**inputs)
    response = _LOOP.run_until_complete(
        complete("qa", prompt, system=qa_prompts.SYSTEM)
    )
    return {"output": response}


def dev_target(inputs: dict) -> dict:
    """
    Eval target for the Dev Agent fix-suggestion step.

    Calls dev_prompts.build_suggestion() with the given inputs and returns the
    raw response string so evaluators can check structural compliance (root
    cause sentence, BEFORE/AFTER blocks, no new imports).

    Note: this evals the build_suggestion() API call only. The build_tdd()
    Claude Code CLI step requires a live repo and is not evaled here.

    Args:
        inputs: Keys matching dev_prompts.build_suggestion() parameters.

    Returns:
        {"output": raw LLM response string}
    """
    prompt = dev_prompts.build_suggestion(**inputs)
    response = _LOOP.run_until_complete(
        complete("dev", prompt)
    )
    return {"output": response}


# ---------------------------------------------------------------------------
# Eval runners
# ---------------------------------------------------------------------------

def run_crash_handler_eval(client: Client, experiment_prefix: str) -> float:
    """
    Run the crash handler eval suite and return the mean score across all
    evaluators and examples.

    Args:
        client:            Authenticated LangSmith client.
        experiment_prefix: Prefix for the LangSmith experiment name.

    Returns:
        Mean score in [0.0, 1.0].
    """
    dataset_name = "helix-crash-handler"
    upsert_dataset(client, dataset_name, CRASH_HANDLER_EXAMPLES)

    results = evaluate(
        crash_handler_target,
        data=dataset_name,
        evaluators=[
            valid_json_crash_handler,
            has_required_crash_fields,
            valid_severity,
            correct_error_type,
        ],
        experiment_prefix=experiment_prefix,
        max_concurrency=1,  # sequential to avoid rate limits on small runs
    )

    return _mean_score(results)


def run_dev_eval(client: Client, experiment_prefix: str) -> float:
    """
    Run the Dev Agent fix-suggestion eval suite and return the mean score.

    Args:
        client:            Authenticated LangSmith client.
        experiment_prefix: Prefix for the LangSmith experiment name.

    Returns:
        Mean score in [0.0, 1.0].
    """
    dataset_name = "helix-dev"
    upsert_dataset(client, dataset_name, DEV_EXAMPLES)

    results = evaluate(
        dev_target,
        data=dataset_name,
        evaluators=[
            has_root_cause_sentence,
            has_before_block,
            has_after_block,
            after_block_differs_from_before,
            no_new_imports_in_fix,
        ],
        experiment_prefix=experiment_prefix,
        max_concurrency=1,
    )

    return _mean_score(results)


def run_qa_eval(client: Client, experiment_prefix: str) -> float:
    """
    Run the QA agent eval suite and return the mean score.

    Args:
        client:            Authenticated LangSmith client.
        experiment_prefix: Prefix for the LangSmith experiment name.

    Returns:
        Mean score in [0.0, 1.0].
    """
    dataset_name = "helix-qa"
    upsert_dataset(client, dataset_name, QA_EXAMPLES)

    results = evaluate(
        qa_target,
        data=dataset_name,
        evaluators=[
            valid_json_qa,
            has_required_qa_fields,
            test_content_not_empty,
            test_avoids_exception_assertion,
        ],
        experiment_prefix=experiment_prefix,
        max_concurrency=1,
    )

    return _mean_score(results)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mean_score(results) -> float:
    """
    Compute the mean evaluator score across all results.

    Args:
        results: The object returned by langsmith.evaluation.evaluate().

    Returns:
        Mean score in [0.0, 1.0], or 0.0 if no scores are available.
    """
    scores = []
    for result in results:
        for feedback in (result.get("evaluation_results", {}).get("results") or []):
            if hasattr(feedback, "score") and feedback.score is not None:
                scores.append(float(feedback.score))
    return sum(scores) / len(scores) if scores else 0.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """
    Parse CLI arguments, run the requested evals, and return an exit code.

    Returns:
        0 if all evals pass the threshold, 1 if any fail, 2 on config error.
    """
    parser = argparse.ArgumentParser(
        description="Run Helix agent evals via LangSmith",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--agent",
        choices=["crash_handler", "qa", "dev"],
        help="Run evals for a single agent only (default: all agents)",
    )
    parser.add_argument(
        "--dataset-only",
        action="store_true",
        help="Upload/update datasets but skip LLM calls and scoring",
    )
    parser.add_argument(
        "--experiment",
        default="",
        help="Custom experiment name prefix (default: helix-eval-<timestamp>)",
    )
    args = parser.parse_args()

    ls_cfg = get_langsmith_config()
    if not ls_cfg.api_key:
        print("ERROR: LANGSMITH_API_KEY is not set.", file=sys.stderr)
        print("Set it to your LangSmith API key and retry.", file=sys.stderr)
        return 2

    client = Client(api_key=ls_cfg.api_key, api_url=ls_cfg.endpoint)
    experiment_prefix = args.experiment or f"helix-eval-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}"

    agents_to_run = [args.agent] if args.agent else ["crash_handler", "qa", "dev"]

    if args.dataset_only:
        print("Dataset-only mode — uploading examples, skipping LLM calls.\n")
        for agent in agents_to_run:
            print(f"[{agent}]")
            if agent == "crash_handler":
                upsert_dataset(client, "helix-crash-handler", CRASH_HANDLER_EXAMPLES)
            elif agent == "qa":
                upsert_dataset(client, "helix-qa", QA_EXAMPLES)
            elif agent == "dev":
                upsert_dataset(client, "helix-dev", DEV_EXAMPLES)
            print()
        return 0

    print(f"Running evals — experiment prefix: {experiment_prefix}\n")

    scores: dict[str, float] = {}
    for agent in agents_to_run:
        print(f"[{agent}]")
        if agent == "crash_handler":
            score = run_crash_handler_eval(client, experiment_prefix)
        elif agent == "qa":
            score = run_qa_eval(client, experiment_prefix)
        elif agent == "dev":
            score = run_dev_eval(client, experiment_prefix)
        else:
            continue
        scores[agent] = score
        status = "PASS" if score >= _PASS_THRESHOLD else "FAIL"
        print(f"  Mean score: {score:.2f}  [{status}]\n")

    all_passed = all(s >= _PASS_THRESHOLD for s in scores.values())
    if not all_passed:
        failed = [a for a, s in scores.items() if s < _PASS_THRESHOLD]
        print(f"FAILED: {failed} — scores below threshold {_PASS_THRESHOLD}", file=sys.stderr)
        return 1

    print(f"All evals passed (threshold: {_PASS_THRESHOLD})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
