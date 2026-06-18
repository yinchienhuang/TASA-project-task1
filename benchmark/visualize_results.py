#!/usr/bin/env python3
"""
Visualize NOTOS Benchmark Results with matplotlib and plotly.

Usage:
    python benchmark/visualize_results.py
"""
import json
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path

benchmark_root = Path(__file__).parent

# Load results
with open(benchmark_root / "results" / "results.json", encoding="utf-8") as f:
    results = json.load(f)

metadata = results["metadata"]
category_data = results["category_breakdown"]

# Extract data
spec_mean = metadata["specialized_mean"]
rag_mean = metadata["rag_mean"]
spec_correct = metadata["specialized_correct"]
rag_correct = metadata["rag_correct"]
spec_partial = metadata["specialized_partial"]
rag_partial = metadata["rag_partial"]
total = metadata["total_questions"]

categories = sorted(category_data.keys())
spec_scores = [category_data[cat]["specialized_mean"] for cat in categories]
rag_scores = [category_data[cat]["rag_mean"] for cat in categories]

# Create figure with subplots
fig = plt.figure(figsize=(16, 12))
fig.suptitle("NOTOS Benchmark: Specialized vs General RAG", fontsize=20, fontweight="bold")

# 1. Overall Score Comparison
ax1 = plt.subplot(2, 3, 1)
x_pos = np.arange(2)
scores = [spec_mean, rag_mean]
colors = ["#2ecc71", "#e74c3c"]  # Green for Specialized, Red for RAG
bars = ax1.bar(x_pos, scores, color=colors, alpha=0.8, edgecolor="black", linewidth=2)
ax1.set_ylabel("Mean Score", fontsize=12, fontweight="bold")
ax1.set_title("Overall Performance", fontsize=14, fontweight="bold")
ax1.set_xticks(x_pos)
ax1.set_xticklabels(["Specialized", "General RAG"])
ax1.set_ylim(0, 1)
ax1.grid(axis="y", alpha=0.3)

# Add score labels on bars
for bar, score in zip(bars, scores):
    height = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width()/2., height,
             f'{score:.3f}', ha='center', va='bottom', fontsize=12, fontweight="bold")

# 2. Correct/Partial/Wrong Distribution
ax2 = plt.subplot(2, 3, 2)
categories_dist = ["Correct\n(1.0)", "Partial\n(0.5)", "Wrong\n(0.0)"]
x = np.arange(len(categories_dist))
width = 0.35

spec_dist = [spec_correct, spec_partial, metadata["specialized_wrong"]]
rag_dist = [rag_correct, rag_partial, metadata["rag_wrong"]]

bars1 = ax2.bar(x - width/2, spec_dist, width, label="Specialized", color="#2ecc71", alpha=0.8, edgecolor="black")
bars2 = ax2.bar(x + width/2, rag_dist, width, label="General RAG", color="#e74c3c", alpha=0.8, edgecolor="black")

ax2.set_ylabel("Number of Questions", fontsize=12, fontweight="bold")
ax2.set_title("Answer Quality Distribution", fontsize=14, fontweight="bold")
ax2.set_xticks(x)
ax2.set_xticklabels(categories_dist)
ax2.legend(fontsize=10)
ax2.grid(axis="y", alpha=0.3)

# Add count labels
for bars in [bars1, bars2]:
    for bar in bars:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                 f'{int(height)}', ha='center', va='bottom', fontsize=10)

# 3. Category Performance Comparison
ax3 = plt.subplot(2, 3, 3)
x = np.arange(len(categories))
width = 0.35

bars1 = ax3.bar(x - width/2, spec_scores, width, label="Specialized", color="#2ecc71", alpha=0.8, edgecolor="black")
bars2 = ax3.bar(x + width/2, rag_scores, width, label="General RAG", color="#e74c3c", alpha=0.8, edgecolor="black")

ax3.set_ylabel("Mean Score", fontsize=12, fontweight="bold")
ax3.set_title("Performance by Category", fontsize=14, fontweight="bold")
ax3.set_xticks(x)
ax3.set_xticklabels([cat.split(" ")[0] for cat in categories], rotation=45, ha="right")
ax3.set_ylim(0, 1.1)
ax3.legend(fontsize=10)
ax3.grid(axis="y", alpha=0.3)

# 4. Category Winners (Pie Chart)
ax4 = plt.subplot(2, 3, 4)
spec_wins = sum(1 for i in range(len(categories)) if spec_scores[i] > rag_scores[i])
rag_wins = sum(1 for i in range(len(categories)) if rag_scores[i] > spec_scores[i])
ties = sum(1 for i in range(len(categories)) if spec_scores[i] == rag_scores[i])

sizes = [spec_wins, rag_wins, ties]
labels = [f"Specialized\n({spec_wins})", f"RAG\n({rag_wins})", f"Tied\n({ties})"]
colors = ["#2ecc71", "#e74c3c", "#95a5a6"]

wedges, texts, autotexts = ax4.pie(sizes, labels=labels, colors=colors, autopct="%1.0f%%",
                                     startangle=90, textprops={"fontsize": 11, "fontweight": "bold"})
ax4.set_title("Category Wins", fontsize=14, fontweight="bold")

# 5. Detailed Category Breakdown (Table)
ax5 = plt.subplot(2, 3, 5)
ax5.axis("off")

table_data = []
table_data.append(["Category", "Specialized", "RAG", "Winner"])
for i, cat in enumerate(categories):
    s_score = spec_scores[i]
    r_score = rag_scores[i]
    if s_score > r_score:
        winner = "S +"
    elif r_score > s_score:
        winner = "R +"
    else:
        winner = "Tie"

    table_data.append([
        cat.split(" ")[0],
        f"{s_score:.3f}",
        f"{r_score:.3f}",
        winner
    ])

table = ax5.table(cellText=table_data, cellLoc="center", loc="center",
                  colWidths=[0.3, 0.23, 0.23, 0.2])
table.auto_set_font_size(False)
table.set_fontsize(10)
table.scale(1, 2)

# Style header row
for i in range(4):
    table[(0, i)].set_facecolor("#34495e")
    table[(0, i)].set_text_props(weight="bold", color="white")

# Alternate row colors
for i in range(1, len(table_data)):
    for j in range(4):
        if i % 2 == 0:
            table[(i, j)].set_facecolor("#ecf0f1")
        else:
            table[(i, j)].set_facecolor("#ffffff")

ax5.set_title("Category Scores", fontsize=14, fontweight="bold", pad=20)

# 6. Key Metrics Summary
ax6 = plt.subplot(2, 3, 6)
ax6.axis("off")

summary_text = f"""
BENCHMARK SUMMARY

Winner: SPECIALIZED +

Overall Scores:
  Specialized: {spec_mean:.3f}
  General RAG: {rag_mean:.3f}
  Margin: +{spec_mean - rag_mean:.3f}

Correct Answers:
  Specialized: {spec_correct}/{total}
  General RAG: {rag_correct}/{total}

Partial Correct:
  Specialized: {spec_partial}
  General RAG: {rag_partial}

Category Performance:
  Specialized wins: {spec_wins}/{len(categories)}
  RAG wins: {rag_wins}/{len(categories)}
  Tied: {ties}/{len(categories)}

Key Finding:
Specialized system demonstrates
superior domain-aware reasoning
across most categories.
"""

ax6.text(0.05, 0.95, summary_text, transform=ax6.transAxes,
         fontsize=11, verticalalignment="top", fontfamily="monospace",
         bbox=dict(boxstyle="round", facecolor="#ecf0f1", alpha=0.8, pad=1))

plt.tight_layout()
plt.savefig(benchmark_root / "results" / "benchmark_visualization.png", dpi=300, bbox_inches="tight")
print(f"Saved: {benchmark_root / 'results' / 'benchmark_visualization.png'}")

# Also save individual plots
# Category comparison detail
fig2, ax = plt.subplots(figsize=(12, 6))
x = np.arange(len(categories))
width = 0.35

bars1 = ax.bar(x - width/2, spec_scores, width, label="Specialized", color="#2ecc71", alpha=0.8, edgecolor="black", linewidth=1.5)
bars2 = ax.bar(x + width/2, rag_scores, width, label="General RAG", color="#e74c3c", alpha=0.8, edgecolor="black", linewidth=1.5)

ax.set_ylabel("Mean Score", fontsize=14, fontweight="bold")
ax.set_xlabel("Category", fontsize=14, fontweight="bold")
ax.set_title("NOTOS Benchmark: Category-by-Category Comparison", fontsize=16, fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(categories, rotation=45, ha="right", fontsize=12)
ax.set_ylim(0, 1.1)
ax.legend(fontsize=12, loc="upper right")
ax.grid(axis="y", alpha=0.3, linestyle="--")

# Add value labels on bars
for bars in [bars1, bars2]:
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.3f}', ha='center', va='bottom', fontsize=10, fontweight="bold")

plt.tight_layout()
plt.savefig(benchmark_root / "results" / "category_comparison.png", dpi=300, bbox_inches="tight")
print(f"Saved: {benchmark_root / 'results' / 'category_comparison.png'}")

print("\nVisualization complete!")
print(f"Open the PNG files in benchmark/results/ to view the charts")
