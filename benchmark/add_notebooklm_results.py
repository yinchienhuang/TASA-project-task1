#!/usr/bin/env python3
"""
Add NotebookLM scores to results.json for comparison.

Usage:
    python benchmark/add_notebooklm_results.py --interactive    # Interactive input
    python benchmark/add_notebooklm_results.py --file scores.json # Load from file
"""
import json
import argparse
import sys
from pathlib import Path
from collections import defaultdict


def interactive_input():
    """Interactively input NotebookLM scores for each question."""
    results_path = Path(__file__).parent / "results" / "results.json"

    with open(results_path) as f:
        results = json.load(f)

    detailed_results = results["detailed_results"]
    notebooklm_scores = {}

    print("=" * 70)
    print("Enter NotebookLM scores for each question (0-1, or 'skip' to leave blank)")
    print("=" * 70)
    print()

    for item in detailed_results:
        qid = item["id"]
        question = item["question"][:60] + "..." if len(item["question"]) > 60 else item["question"]
        ground_truth = item["ground_truth"]

        print(f"\nQuestion {qid}: {question}")
        print(f"Ground Truth: {ground_truth}")
        print(f"Specialized: {item['specialized_answer'][:50]}..." if len(item['specialized_answer']) > 50 else f"Specialized: {item['specialized_answer']}")
        print(f"RAG: {item['rag_answer'][:50]}..." if len(item['rag_answer']) > 50 else f"RAG: {item['rag_answer']}")

        while True:
            score_input = input(f"NotebookLM score for {qid}: ").strip()

            if score_input.lower() == 'skip':
                notebooklm_scores[qid] = None
                print("  → Skipped")
                break

            try:
                score = float(score_input)
                if 0 <= score <= 1:
                    notebooklm_scores[qid] = score
                    print(f"  → Recorded: {score}")
                    break
                else:
                    print("  Please enter a value between 0 and 1")
            except ValueError:
                print("  Please enter a valid number or 'skip'")

    return notebooklm_scores


def load_from_file(filepath):
    """Load NotebookLM scores from a JSON file.

    Expected format:
    {
        "a01": 1.0,
        "a02": 0.5,
        ...
    }
    """
    with open(filepath) as f:
        return json.load(f)


def add_scores_to_results(notebooklm_scores):
    """Add NotebookLM scores to results.json."""
    results_path = Path(__file__).parent / "results" / "results.json"

    with open(results_path) as f:
        results = json.load(f)

    # Add notebooklm_answer and notebooklm_score to each question
    for item in results["detailed_results"]:
        qid = item["id"]
        score = notebooklm_scores.get(qid)

        if score is not None:
            item["notebooklm_score"] = score
            item["notebooklm_answer"] = f"[Score: {score}]"  # Placeholder

    # Add NotebookLM scores dict to results
    notebooklm_scores_filtered = {k: v for k, v in notebooklm_scores.items() if v is not None}
    results["notebooklm_scores"] = notebooklm_scores_filtered

    # Calculate NotebookLM metrics
    if notebooklm_scores_filtered:
        scores_list = list(notebooklm_scores_filtered.values())
        correct = sum(1 for s in scores_list if s >= 1.0)
        partial = sum(1 for s in scores_list if 0 < s < 1.0)
        wrong = sum(1 for s in scores_list if s == 0)
        mean = sum(scores_list) / len(scores_list) if scores_list else 0

        results["metadata"]["notebooklm_mean"] = mean
        results["metadata"]["notebooklm_correct"] = correct
        results["metadata"]["notebooklm_partial"] = partial
        results["metadata"]["notebooklm_wrong"] = wrong

    # Calculate category breakdown for NotebookLM
    category_breakdown = defaultdict(lambda: [])

    for item in results["detailed_results"]:
        if "notebooklm_score" in item:
            cat = item.get("category", "unknown")
            category_breakdown[cat].append(item["notebooklm_score"])

    for cat, scores in category_breakdown.items():
        if cat in results["category_breakdown"] and scores:
            results["category_breakdown"][cat]["notebooklm_mean"] = sum(scores) / len(scores)
            results["category_breakdown"][cat]["notebooklm_count"] = len(scores)

    # Save updated results
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Results saved to {results_path}")

    if notebooklm_scores_filtered:
        print(f"\nNotebookLM Statistics:")
        print(f"  Mean Score: {mean:.3f}")
        print(f"  Correct: {correct}/{len(scores_list)}")
        print(f"  Partial: {partial}/{len(scores_list)}")
        print(f"  Wrong: {wrong}/{len(scores_list)}")


def main():
    parser = argparse.ArgumentParser(
        description="Add NotebookLM scores to benchmark results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python benchmark/add_notebooklm_results.py --interactive    # Input scores manually
  python benchmark/add_notebooklm_results.py --file scores.json # Load from JSON file

JSON file format:
  {
    "a01": 1.0,
    "a02": 0.5,
    "a03": 0.0,
    ...
  }
        """
    )

    parser.add_argument("--interactive", action="store_true", help="Interactively input scores")
    parser.add_argument("--file", type=str, help="Load scores from JSON file")

    args = parser.parse_args()

    if not args.interactive and not args.file:
        parser.print_help()
        sys.exit(1)

    if args.interactive:
        notebooklm_scores = interactive_input()
    elif args.file:
        notebooklm_scores = load_from_file(args.file)
        print(f"[OK] Loaded {len(notebooklm_scores)} scores from {args.file}")

    add_scores_to_results(notebooklm_scores)


if __name__ == "__main__":
    main()
