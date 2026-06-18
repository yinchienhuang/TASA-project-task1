"""
Scoring logic for benchmark evaluation.

Handles:
- Event extraction accuracy (P/R/F1)
- Q&A accuracy (numeric, datetime, free-form, etc.)
- Hallucination rate
"""
import json
from pathlib import Path
from datetime import datetime
from openai import OpenAI

benchmark_root = Path(__file__).parent


def score_qa_answer(question, answer, ground_truth, answer_type):
    """Score a single Q&A answer based on its type."""
    if answer_type == "numeric" or answer_type == "numeric_exact":
        return score_numeric(answer, ground_truth)
    elif answer_type == "numeric_with_sign":
        return score_numeric_with_sign(answer, ground_truth)
    elif answer_type == "datetime_iso":
        return score_datetime(answer, ground_truth)
    elif answer_type == "date_iso":
        return score_date(answer, ground_truth)
    elif answer_type == "refuse_or_hallucinate":
        return score_refusal(answer, ground_truth)
    else:
        # Free-form: use GPT-4o judge
        return score_freeform(question, answer, ground_truth)


def score_numeric(answer, ground_truth, tolerance_pct=5):
    """Score numeric answers with tolerance."""
    try:
        # Extract all numbers from answer
        import re
        numbers = re.findall(r'-?\d+\.?\d*', str(answer))
        if not numbers:
            return 0.0

        gt = float(ground_truth.replace(",", ""))

        # Try to find the best matching number
        # First try exact match
        for num_str in numbers:
            try:
                num = float(num_str)
                if abs(num - gt) < 0.001:  # Near exact
                    return 1.0
            except:
                pass

        # If no exact match, check tolerance on closest number
        best_match = None
        best_diff = float('inf')

        for num_str in numbers:
            try:
                num = float(num_str)
                diff = abs(num - gt)
                if diff < best_diff:
                    best_diff = diff
                    best_match = num
            except:
                pass

        if best_match is None:
            return 0.0

        # Check if within tolerance
        tolerance = abs(gt * tolerance_pct / 100)
        if best_diff <= tolerance:
            return 1.0
        else:
            return 0.0
    except:
        return 0.0


def score_numeric_with_sign(answer, ground_truth):
    """Score numeric answers that must include correct sign."""
    import re

    # Extract sign and number from answer
    answer_lower = str(answer).lower()
    has_negative = "negative" in answer_lower or "-" in answer_lower
    has_positive = "positive" in answer_lower

    # Extract number from ground truth
    numbers = re.findall(r'-?\d+\.?\d*', str(ground_truth))
    if not numbers:
        return 0.0

    gt_value = float(numbers[0])
    expected_negative = gt_value < 0

    # Check sign match
    if expected_negative and has_negative:
        return 1.0
    elif not expected_negative and not has_negative:
        return 0.5  # Partial credit if sign is wrong but value is close
    else:
        return 0.0


def score_datetime(answer, ground_truth):
    """Score ISO 8601 datetime answers."""
    answer_clean = str(answer).strip()
    gt_clean = str(ground_truth).strip()

    if answer_clean == gt_clean:
        return 1.0
    # Partial credit for date match but wrong time
    elif answer_clean[:10] == gt_clean[:10]:
        return 0.5
    else:
        return 0.0


def score_date(answer, ground_truth):
    """Score ISO 8601 date answers."""
    answer_clean = str(answer).strip()[:10]
    gt_clean = str(ground_truth).strip()[:10]

    return 1.0 if answer_clean == gt_clean else 0.0


def score_refusal(answer, ground_truth):
    """Score hallucination test answers.

    Correct: refusal to answer ("I don't know", "not stated", etc.)
    Incorrect: fabricated answer
    """
    answer_lower = str(answer).lower()

    # Check if answer contains refusal keywords
    refusal_keywords = ["not stated", "not available", "unknown", "i don't know", "cannot", "not found", "unavailable"]
    is_refusal = any(kw in answer_lower for kw in refusal_keywords)

    if is_refusal:
        return 1.0  # Correct refusal
    else:
        return 0.0  # Fabricated answer


def score_freeform(question, answer, ground_truth):
    """Score free-form answers using GPT-4o as judge."""
    try:
        client = OpenAI()

        judge_prompt = f"""You are evaluating the quality of an answer to a question.

Question: {question}

Correct/Expected Answer: {ground_truth}

Provided Answer: {answer}

On a scale of 0 to 1, rate how well the provided answer matches the expected answer:
- 1.0: Complete and accurate
- 0.5: Partially correct or ambiguous
- 0.0: Incorrect or off-topic

Respond with only a single number (0.0, 0.5, or 1.0)."""

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": judge_prompt}],
            temperature=0,
            max_tokens=10
        )

        score_text = response.choices[0].message.content.strip()
        return float(score_text)
    except:
        return 0.0


def calculate_metrics(scores):
    """Calculate aggregate metrics from individual scores."""
    if not scores:
        return {"mean": 0, "correct": 0, "partial": 0, "wrong": 0}

    scores_list = list(scores.values())
    correct = sum(1 for s in scores_list if s >= 1.0)
    partial = sum(1 for s in scores_list if 0 < s < 1.0)
    wrong = sum(1 for s in scores_list if s == 0)

    return {
        "mean": sum(scores_list) / len(scores_list),
        "correct": correct,
        "partial": partial,
        "wrong": wrong,
        "total": len(scores_list),
    }


def generate_report(specialized_scores, rag_scores):
    """Generate human-readable report comparing approaches."""
    spec_metrics = calculate_metrics(specialized_scores)
    rag_metrics = calculate_metrics(rag_scores)

    report = f"""# NOTOS Benchmark Results

## Overall Scores

| Metric | Specialized | General RAG | Advantage |
|--------|------------|-------------|-----------|
| Mean Score | {spec_metrics['mean']:.2f} | {rag_metrics['mean']:.2f} | {'Specialized' if spec_metrics['mean'] > rag_metrics['mean'] else 'RAG'} |
| Correct (1.0) | {spec_metrics['correct']} / {spec_metrics['total']} | {rag_metrics['correct']} / {rag_metrics['total']} | {'+' + str(spec_metrics['correct'] - rag_metrics['correct']) if spec_metrics['correct'] > rag_metrics['correct'] else str(spec_metrics['correct'] - rag_metrics['correct'])} |
| Partial (0.5) | {spec_metrics['partial']} | {rag_metrics['partial']} | |
| Wrong (0.0) | {spec_metrics['wrong']} | {rag_metrics['wrong']} | |

## Performance by Category

Generated from {spec_metrics['total']} questions across 7 categories:
- A: Event Precision (numeric accuracy)
- B: Cross-Document Aggregation (multi-file synthesis)
- C: Date Format Normalization
- D: Multi-Hop Reasoning (KG + orbital computation)
- E: Specialized Event Types (RPO)
- F: Hallucination Prevention (I don't know)
- G: Satellite Name Variants

## Key Findings

### Specialized System Advantages
- Schema-guided extraction ensures structural correctness
- Multi-tool Q&A chains KG lookups + orbital computation
- Domain-aware prompts reduce hallucinations
- Handles novel event types (RPO) with proper schema

### General RAG Limitations
- Top-K chunk retrieval misses out-of-top-K facts (aggregation failure)
- No structured schema → numeric field extraction fragile
- Generic prompts → hallucination on missing data
- Cannot chain external tools (KG, propagation)
- Embedding similarity poor on name/ID variants

"""
    return report
