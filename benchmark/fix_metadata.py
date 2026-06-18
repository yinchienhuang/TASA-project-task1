#!/usr/bin/env python3
"""Fix metadata in results.json by recalculating from detailed_results."""
import json
from pathlib import Path

benchmark_root = Path(__file__).parent
results_path = benchmark_root / "results" / "results.json"

with open(results_path) as f:
    results = json.load(f)

detailed_results = results.get("detailed_results", [])

# Calculate metrics from detailed results
spec_scores = []
rag_scores = []

for item in detailed_results:
    spec_scores.append(item.get("specialized_score", 0))
    rag_scores.append(item.get("rag_score", 0))

# Count correct/partial/wrong
spec_correct = sum(1 for s in spec_scores if s >= 1.0)
spec_partial = sum(1 for s in spec_scores if 0 < s < 1.0)
spec_wrong = sum(1 for s in spec_scores if s == 0)

rag_correct = sum(1 for s in rag_scores if s >= 1.0)
rag_partial = sum(1 for s in rag_scores if 0 < s < 1.0)
rag_wrong = sum(1 for s in rag_scores if s == 0)

# Calculate means
spec_mean = sum(spec_scores) / len(spec_scores) if spec_scores else 0
rag_mean = sum(rag_scores) / len(rag_scores) if rag_scores else 0

# Recalculate category breakdown
from collections import defaultdict
category_breakdown = defaultdict(lambda: {"specialized": [], "rag": []})

for item in detailed_results:
    cat = item.get("category", "unknown")
    category_breakdown[cat]["specialized"].append(item.get("specialized_score", 0))
    category_breakdown[cat]["rag"].append(item.get("rag_score", 0))

# Convert to final format
final_breakdown = {}
for cat, scores in category_breakdown.items():
    spec_list = scores["specialized"]
    rag_list = scores["rag"]
    final_breakdown[cat] = {
        "specialized_mean": sum(spec_list) / len(spec_list) if spec_list else 0,
        "rag_mean": sum(rag_list) / len(rag_list) if rag_list else 0,
        "count": len(spec_list)
    }

# Update metadata
results["metadata"].update({
    "specialized_mean": spec_mean,
    "rag_mean": rag_mean,
    "specialized_correct": spec_correct,
    "specialized_partial": spec_partial,
    "specialized_wrong": spec_wrong,
    "rag_correct": rag_correct,
    "rag_partial": rag_partial,
    "rag_wrong": rag_wrong,
    "advantage": "Specialized" if spec_mean > rag_mean else "RAG" if rag_mean > spec_mean else "Tied",
})

# Update category breakdown
results["category_breakdown"] = final_breakdown

# Save
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"[OK] Updated metadata in {results_path}")
print(f"Specialized: {spec_mean:.3f} ({spec_correct} correct, {spec_partial} partial, {spec_wrong} wrong)")
print(f"RAG: {rag_mean:.3f} ({rag_correct} correct, {rag_partial} partial, {rag_wrong} wrong)")
