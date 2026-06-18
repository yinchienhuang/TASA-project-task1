#!/usr/bin/env python3
"""
Build ground truth by having Claude Sonnet carefully annotate each question.

This generates benchmark/ground_truth.json which MUST be manually reviewed
and corrected before use as the official standard.

Usage:
    python benchmark/build_ground_truth.py
"""
import json
import sys
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# Load environment
backend_env = Path(__file__).parent.parent / "backend" / ".env"
if backend_env.exists():
    load_dotenv(backend_env)

benchmark_root = Path(__file__).parent


def load_questions():
    """Load test questions."""
    with open(benchmark_root / "questions.json") as f:
        return json.load(f).get("questions", [])


def load_events():
    """Load extracted events from benchmark data."""
    with open(benchmark_root / "data" / "events.json") as f:
        return json.load(f).get("events", [])


def annotate_question(client, question_obj, events):
    """Have Claude Sonnet annotate a single question with ground truth."""
    question = question_obj["question"]

    # Build context for the annotator
    context = f"""You are an expert annotator for a satellite tracking and analysis benchmark.
Your task is to provide the GROUND TRUTH answer to this question based on the extracted events.

## Extracted Events Summary
Total events: {len(events)}
- Maneuvers: {sum(1 for e in events if e.get('type') == 'maneuver')}
- Photometric Changes: {sum(1 for e in events if e.get('type') == 'photometric_change')}
- Launches: {sum(1 for e in events if e.get('type') == 'launch')}

Unique satellites: {len(set(e.get('satellite_id') for e in events if e.get('satellite_id')))}

## Question
{question}

## Your Task
Based on the extracted events, provide the correct answer to this question.
- Be precise and specific
- Include numeric values when relevant
- Format dates as ISO 8601 (YYYY-MM-DDTHH:MM:SSZ)
- If the answer cannot be determined from the events, say "NOT STATED IN EVENTS"

Respond with ONLY the ground truth answer, no explanation."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": context}],
        temperature=0,
        max_tokens=500
    )
    return response.choices[0].message.content.strip()


def main():
    """Build ground truth for all questions."""
    print("=" * 60)
    print("Building Ground Truth with GPT-4o")
    print("=" * 60)

    questions = load_questions()
    events = load_events()

    if not questions:
        print("Error: No questions found in questions.json")
        sys.exit(1)

    if not events:
        print("Error: No events found in data/events.json")
        print("Please run: python benchmark/setup.py")
        sys.exit(1)

    print(f"\nLoaded {len(questions)} questions")
    print(f"Loaded {len(events)} events")
    print("\n[WARNING] This will be manually reviewed before use.")
    print("=" * 60)

    client = OpenAI()
    ground_truth = []

    for i, q in enumerate(questions, 1):
        qid = q.get("id", f"q{i}")
        question_preview = q["question"][:60]
        print(f"\n[{i}/{len(questions)}] {qid}: {question_preview}...", end=" ", flush=True)

        try:
            answer = annotate_question(client, q, events)
            print("[OK]")

            ground_truth.append({
                "id": qid,
                "question": q["question"],
                "category": q.get("category", ""),
                "answer_type": q.get("answer_type", "free_form"),
                "ground_truth": answer,
                "notes": "[TODO: manual review required]"
            })
        except Exception as e:
            print(f"[ERROR] {e}")
            ground_truth.append({
                "id": qid,
                "question": q["question"],
                "category": q.get("category", ""),
                "ground_truth": f"ERROR: {e}",
                "notes": "[FAILED - needs manual review]"
            })

    # Save ground truth
    gt_file = benchmark_root / "ground_truth.json"
    with open(gt_file, "w") as f:
        json.dump({
            "metadata": {
                "total_questions": len(questions),
                "status": "REQUIRES MANUAL REVIEW",
                "instructions": "Please review each answer carefully. This is the ground truth standard for the benchmark."
            },
            "ground_truth": ground_truth
        }, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"Ground truth saved to: {gt_file}")
    print(f"{'=' * 60}")
    print("\n[IMPORTANT] NEXT STEPS:")
    print("1. Open ground_truth.json in an editor")
    print("2. Review each answer carefully")
    print("3. Correct any errors")
    print("4. Once review is complete, you can run benchmark:")
    print("   python benchmark/run_benchmark.py")


if __name__ == "__main__":
    main()
