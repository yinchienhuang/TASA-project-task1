#!/usr/bin/env python3
"""
Run NOTOS benchmark: Specialized vs General RAG.

Compares:
1. Specialized system (schema-guided extraction + multi-tool Q&A)
2. General RAG (embedding-based retrieval + generic GPT-4o)

Usage:
    python benchmark/run_benchmark.py
    python benchmark/run_benchmark.py --ids d01,d02,d03,e01

Requirements:
    - benchmark/setup.py already run (creates data/events.json, rag_corpus/)
    - benchmark/ground_truth.json exists and is manually reviewed
    - OpenAI API key in backend/.env
"""
import asyncio
import json
import sys
import os
import argparse
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

# Load environment
backend_env = Path(__file__).parent.parent / "backend" / ".env"
if backend_env.exists():
    load_dotenv(backend_env)

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

benchmark_root = Path(__file__).parent

# Import our benchmark approaches
from approaches import specialized, general_rag
from evaluate import (
    score_qa_answer,
    calculate_metrics,
    generate_report,
)


def load_ground_truth():
    """Load manually-reviewed ground truth."""
    gt_file = benchmark_root / "ground_truth.json"
    if not gt_file.exists():
        print(f"Error: {gt_file} not found.")
        print("Please run: python benchmark/build_ground_truth.py")
        print("Then review and fix ground_truth.json")
        sys.exit(1)

    with open(gt_file) as f:
        data = json.load(f)
    return data.get("ground_truth", [])


def load_questions():
    """Load test questions."""
    with open(benchmark_root / "questions.json") as f:
        return json.load(f).get("questions", [])


def load_data():
    """Load benchmark data (events, RAG corpus)."""
    events_file = benchmark_root / "data" / "events.json"
    rag_dir = benchmark_root / "data" / "rag_corpus"

    if not events_file.exists():
        print(f"Error: {events_file} not found.")
        print("Please run: python benchmark/setup.py")
        sys.exit(1)

    with open(events_file) as f:
        events = json.load(f).get("events", [])

    # Load RAG corpus if available
    rag_corpus = None
    if rag_dir.exists():
        try:
            rag_corpus = general_rag.load_rag_corpus(rag_dir)
        except Exception as e:
            print(f"Warning: Could not load RAG corpus: {e}")

    return events, rag_corpus


async def run_benchmark(ran_partial=False, all_questions_loader=None):
    """Run full benchmark comparison."""
    print("=" * 70)
    print("NOTOS Benchmark: Specialized vs General RAG")
    print("=" * 70)

    # Load data
    print("\n1. Loading data...")
    questions = load_questions()
    ground_truth = load_ground_truth()
    events, rag_corpus = load_data()

    print(f"   Questions: {len(questions)}")
    print(f"   Ground truth: {len(ground_truth)}")
    print(f"   Events: {len(events)}")
    print(f"   RAG corpus: {'available' if rag_corpus else 'not available'}")

    # Verify ground truth has all questions
    gt_ids = {gt["id"] for gt in ground_truth}
    q_ids = {q["id"] for q in questions}
    missing = q_ids - gt_ids
    if missing:
        print(f"\nWarning: Missing ground truth for: {missing}")
        print("Please complete ground_truth.json before running benchmark.")
        sys.exit(1)

    # Build GT lookup
    gt_lookup = {gt["id"]: gt for gt in ground_truth}

    print("\n2. Running benchmark on 25 questions...")
    print("-" * 70)

    specialized_scores = {}
    rag_scores = {}
    specialized_answers = {}  # Store actual answers
    rag_answers = {}
    results_by_category = defaultdict(lambda: {"specialized": [], "rag": []})

    # Load benchmark events for specialized approach
    try:
        benchmark_events = specialized.load_benchmark_events()
        benchmark_kg = specialized.load_kg_graph()
    except Exception as e:
        print(f"Warning: Could not load benchmark data: {e}")
        benchmark_events = events
        benchmark_kg = None

    for i, question in enumerate(questions, 1):
        qid = question["id"]
        question_text = question["question"]
        category = question.get("category", "unknown")
        answer_type = question.get("answer_type", "free_form")

        gt = gt_lookup.get(qid)
        if not gt:
            print(f"[{i:2d}/{len(questions)}] {qid}: SKIPPED (no ground truth)")
            continue

        ground_truth_answer = gt.get("ground_truth", "")

        # Progress indicator
        print(f"[{i:2d}/{len(questions)}] {qid}: {question_text[:50]}...", end=" ", flush=True)

        try:
            # Run specialized approach
            try:
                spec_answer = await specialized.answer_question(
                    question_text,
                    benchmark_events,
                    benchmark_kg
                )
            except Exception as e:
                spec_answer = f"ERROR: {str(e)[:100]}"

            # Score specialized answer
            spec_score = score_qa_answer(
                question_text,
                spec_answer,
                ground_truth_answer,
                answer_type
            )
            specialized_scores[qid] = spec_score
            specialized_answers[qid] = spec_answer  # Store actual answer

            # Run RAG approach (if corpus available)
            if rag_corpus:
                try:
                    rag_answer = general_rag.answer_question_rag(
                        question_text,
                        rag_corpus
                    )
                except Exception as e:
                    rag_answer = f"ERROR: {str(e)[:100]}"

                rag_score = score_qa_answer(
                    question_text,
                    rag_answer,
                    ground_truth_answer,
                    answer_type
                )
                rag_scores[qid] = rag_score
                rag_answers[qid] = rag_answer  # Store actual answer
            else:
                rag_answer = "RAG corpus not available"
                rag_score = 0.0
                rag_scores[qid] = rag_score
                rag_answers[qid] = rag_answer

            # Track by category
            results_by_category[category]["specialized"].append(spec_score)
            results_by_category[category]["rag"].append(rag_score)

            # Print result
            print(f"[OK] S:{spec_score:.2f} R:{rag_score:.2f}")

        except Exception as e:
            print(f"[FAIL] {e}")
            specialized_scores[qid] = 0.0
            rag_scores[qid] = 0.0
            results_by_category[category]["specialized"].append(0.0)
            results_by_category[category]["rag"].append(0.0)

    # Calculate metrics
    print("\n" + "=" * 70)
    print("3. Calculating metrics...")
    print("=" * 70)

    spec_metrics = calculate_metrics(specialized_scores)
    rag_metrics = calculate_metrics(rag_scores)

    print("\nOverall Scores:")
    print(f"  Specialized: {spec_metrics['mean']:.3f} ({spec_metrics['correct']}/{spec_metrics['total']} correct)")
    print(f"  General RAG: {rag_metrics['mean']:.3f} ({rag_metrics['correct']}/{rag_metrics['total']} correct)")

    print("\nBy Category:")
    for category in sorted(results_by_category.keys()):
        cat_spec_scores = results_by_category[category]["specialized"]
        cat_rag_scores = results_by_category[category]["rag"]

        spec_mean = sum(cat_spec_scores) / len(cat_spec_scores) if cat_spec_scores else 0
        rag_mean = sum(cat_rag_scores) / len(cat_rag_scores) if cat_rag_scores else 0

        print(f"  {category}: S={spec_mean:.3f} R={rag_mean:.3f} (n={len(cat_spec_scores)})")

    # Generate report
    print("\n4. Generating report...")
    report = generate_report(specialized_scores, rag_scores)

    # Add category breakdown
    report += "\n## Detailed Results by Category\n\n"
    for category in sorted(results_by_category.keys()):
        cat_spec_scores = results_by_category[category]["specialized"]
        cat_rag_scores = results_by_category[category]["rag"]

        spec_mean = sum(cat_spec_scores) / len(cat_spec_scores) if cat_spec_scores else 0
        rag_mean = sum(cat_rag_scores) / len(cat_rag_scores) if cat_rag_scores else 0

        report += f"### {category}\n"
        report += f"- Specialized: {spec_mean:.3f} ({len([s for s in cat_spec_scores if s == 1.0])}/{len(cat_spec_scores)} correct)\n"
        report += f"- General RAG: {rag_mean:.3f} ({len([s for s in cat_rag_scores if s == 1.0])}/{len(cat_rag_scores)} correct)\n"
        report += f"- Advantage: {'Specialized' if spec_mean > rag_mean else 'RAG' if rag_mean > spec_mean else 'Tied'}\n\n"

    # Save results
    results_dir = benchmark_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Load existing results if partial update
    existing_results = None
    results_json_path = results_dir / "results.json"
    if ran_partial and results_json_path.exists():
        try:
            with open(results_json_path) as f:
                existing_results = json.load(f)
            print(f"\n[PARTIAL UPDATE] Loading existing results from {results_json_path}")
        except:
            existing_results = None

    # Save JSON results with answers
    detailed_results = []

    if existing_results and ran_partial:
        # Merge: keep old results for questions not in this run, update those that are
        existing_detailed = {r["id"]: r for r in existing_results.get("detailed_results", [])}

        # Load all questions (use the original loader if provided)
        all_qs = all_questions_loader() if all_questions_loader else load_questions()
        for q in all_qs:
            qid = q["id"]
            if qid in specialized_answers:
                # This was run in this session, use new result
                detailed_results.append({
                    "id": qid,
                    "question": q["question"],
                    "category": q.get("category", ""),
                    "answer_type": q.get("answer_type", ""),
                    "ground_truth": gt_lookup.get(qid, {}).get("ground_truth", ""),
                    "specialized_answer": specialized_answers.get(qid, ""),
                    "specialized_score": specialized_scores.get(qid, 0),
                    "rag_answer": rag_answers.get(qid, ""),
                    "rag_score": rag_scores.get(qid, 0),
                })
            elif qid in existing_detailed:
                # Keep old result
                detailed_results.append(existing_detailed[qid])

        # Merge scores
        all_spec_scores = existing_results.get("specialized_scores", {}).copy()
        all_rag_scores = existing_results.get("rag_scores", {}).copy()
        all_spec_scores.update(specialized_scores)
        all_rag_scores.update(rag_scores)

        # Recalculate metrics from all results
        all_spec_metrics = calculate_metrics(all_spec_scores)
        all_rag_metrics = calculate_metrics(all_rag_scores)

        results_json = {
            "metadata": {
                "total_questions": len(detailed_results),
                "specialized_mean": all_spec_metrics["mean"],
                "rag_mean": all_rag_metrics["mean"],
                "advantage": "Specialized" if all_spec_metrics["mean"] > all_rag_metrics["mean"] else "RAG",
                "specialized_correct": all_spec_metrics["correct"],
                "specialized_partial": all_spec_metrics["partial"],
                "specialized_wrong": all_spec_metrics["wrong"],
                "rag_correct": all_rag_metrics["correct"],
                "rag_partial": all_rag_metrics["partial"],
                "rag_wrong": all_rag_metrics["wrong"],
                "note": f"Partial update: re-ran {len(specialized_scores)} questions, merged with existing {len(existing_results.get('detailed_results', [])) - len(specialized_scores)} results"
            },
            "specialized_scores": all_spec_scores,
            "rag_scores": all_rag_scores,
            "detailed_results": detailed_results,
            "category_breakdown": existing_results.get("category_breakdown", {})  # Keep existing breakdown
        }

        print(f"[MERGED] {len(specialized_scores)} new results + {len(detailed_results) - len(specialized_scores)} existing")
    else:
        # Full run - generate all results
        for q in questions:
            qid = q["id"]
            detailed_results.append({
                "id": qid,
                "question": q["question"],
                "category": q.get("category", ""),
                "answer_type": q.get("answer_type", ""),
                "ground_truth": gt_lookup.get(qid, {}).get("ground_truth", ""),
                "specialized_answer": specialized_answers.get(qid, ""),
                "specialized_score": specialized_scores.get(qid, 0),
                "rag_answer": rag_answers.get(qid, ""),
                "rag_score": rag_scores.get(qid, 0),
            })

        results_json = {
            "metadata": {
                "total_questions": len(questions),
                "specialized_mean": spec_metrics["mean"],
                "rag_mean": rag_metrics["mean"],
                "advantage": "Specialized" if spec_metrics["mean"] > rag_metrics["mean"] else "RAG"
            },
            "specialized_scores": specialized_scores,
            "rag_scores": rag_scores,
            "detailed_results": detailed_results,
            "category_breakdown": {
                cat: {
                    "specialized_mean": sum(v["specialized"]) / len(v["specialized"]) if v["specialized"] else 0,
                    "rag_mean": sum(v["rag"]) / len(v["rag"]) if v["rag"] else 0,
                    "count": len(v["specialized"])
                }
                for cat, v in results_by_category.items()
            }
        }

    with open(results_dir / "results.json", "w") as f:
        json.dump(results_json, f, indent=2, ensure_ascii=False)

    # Save markdown report
    with open(results_dir / "report.md", "w", encoding='utf-8') as f:
        f.write(report)

    print(f"\n[SUCCESS] Results saved to:")
    print(f"  {results_dir / 'results.json'}")
    print(f"  {results_dir / 'report.md'}")

    print("\n" + "=" * 70)
    print("Benchmark complete!")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run NOTOS benchmark with optional question filtering")
    parser.add_argument("--ids", type=str, help="Comma-separated question IDs to run (e.g., 'd01,d02,e01')")
    args = parser.parse_args()

    # Store filter IDs in global scope for run_benchmark to use
    ran_partial = False
    original_load_questions = load_questions  # Save before patching

    if args.ids:
        selected_ids = set(id.strip() for id in args.ids.split(","))
        print(f"Running only questions: {', '.join(sorted(selected_ids))}\n")
        ran_partial = True

        # Monkey-patch load_questions to filter results
        def filtered_load_questions():
            all_questions = original_load_questions()
            return [q for q in all_questions if q["id"] in selected_ids]
        load_questions = filtered_load_questions

    asyncio.run(run_benchmark(ran_partial=ran_partial, all_questions_loader=original_load_questions))
