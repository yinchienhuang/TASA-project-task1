#!/usr/bin/env python3
"""
Visualize benchmark results comparing Specialized, General RAG, and NotebookLM.

Requires:
- results.json with notebooklm_scores populated (use add_notebooklm_results.py)

Usage:
    python benchmark/visualize_three_way.py
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
spec_mean = metadata.get("specialized_mean", 0)
rag_mean = metadata.get("rag_mean", 0)
notebooklm_mean = metadata.get("notebooklm_mean", None)

if notebooklm_mean is None:
    print("Error: NotebookLM scores not found in results.json")
    print("Please run: python benchmark/add_notebooklm_results.py --interactive")
    exit(1)

spec_correct = metadata.get("specialized_correct", 0)
rag_correct = metadata.get("rag_correct", 0)
notebooklm_correct = metadata.get("notebooklm_correct", 0)

spec_partial = metadata.get("specialized_partial", 0)
rag_partial = metadata.get("rag_partial", 0)
notebooklm_partial = metadata.get("notebooklm_partial", 0)

total = metadata.get("total_questions", 25)

# Get categories with all three approaches
categories = sorted([k for k in category_data.keys() if "notebooklm_mean" in category_data[k]])
if not categories:
    print("Warning: No categories have NotebookLM scores yet")
    categories = sorted(category_data.keys())

spec_scores = [category_data[cat].get("specialized_mean", 0) for cat in categories]
rag_scores = [category_data[cat].get("rag_mean", 0) for cat in categories]
notebooklm_scores = [category_data[cat].get("notebooklm_mean", 0) for cat in categories]

# Create figure with subplots
fig = plt.figure(figsize=(18, 12))
fig.suptitle("NOTOS Benchmark: Specialized vs General RAG vs NotebookLM", fontsize=20, fontweight="bold")

# 1. Overall Score Comparison
ax1 = plt.subplot(2, 3, 1)
x_pos = np.arange(3)
scores = [spec_mean, notebooklm_mean, rag_mean]
colors = ["#2ecc71", "#3498db", "#e74c3c"]  # Green, Blue, Red
bars = ax1.bar(x_pos, scores, color=colors, alpha=0.8, edgecolor="black", linewidth=2)
ax1.set_ylabel("Mean Score", fontsize=12, fontweight="bold")
ax1.set_title("Overall Performance", fontsize=14, fontweight="bold")
ax1.set_xticks(x_pos)
ax1.set_xticklabels(["Specialized", "NotebookLM", "General RAG"])
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
width = 0.25

spec_dist = [spec_correct, spec_partial, metadata.get("specialized_wrong", 0)]
notebooklm_dist = [notebooklm_correct, notebooklm_partial, metadata.get("notebooklm_wrong", 0)]
rag_dist = [rag_correct, rag_partial, metadata.get("rag_wrong", 0)]

bars1 = ax2.bar(x - width, spec_dist, width, label="Specialized", color="#2ecc71", alpha=0.8, edgecolor="black")
bars2 = ax2.bar(x, notebooklm_dist, width, label="NotebookLM", color="#3498db", alpha=0.8, edgecolor="black")
bars3 = ax2.bar(x + width, rag_dist, width, label="General RAG", color="#e74c3c", alpha=0.8, edgecolor="black")

ax2.set_ylabel("Number of Questions", fontsize=12, fontweight="bold")
ax2.set_title("Answer Quality Distribution", fontsize=14, fontweight="bold")
ax2.set_xticks(x)
ax2.set_xticklabels(categories_dist)
ax2.legend(fontsize=10)
ax2.grid(axis="y", alpha=0.3)

# Add count labels
for bars in [bars1, bars2, bars3]:
    for bar in bars:
        height = bar.get_height()
        if height > 0:
            ax2.text(bar.get_x() + bar.get_width()/2., height,
                     f'{int(height)}', ha='center', va='bottom', fontsize=9)

# 3. Category Performance Comparison
ax3 = plt.subplot(2, 3, 3)
x = np.arange(len(categories))
width = 0.25

bars1 = ax3.bar(x - width, spec_scores, width, label="Specialized", color="#2ecc71", alpha=0.8, edgecolor="black")
bars2 = ax3.bar(x, notebooklm_scores, width, label="NotebookLM", color="#3498db", alpha=0.8, edgecolor="black")
bars3 = ax3.bar(x + width, rag_scores, width, label="General RAG", color="#e74c3c", alpha=0.8, edgecolor="black")

ax3.set_ylabel("Mean Score", fontsize=12, fontweight="bold")
ax3.set_title("Performance by Category", fontsize=14, fontweight="bold")
ax3.set_xticks(x)
ax3.set_xticklabels([cat.split(" ")[0] for cat in categories], rotation=45, ha="right", fontsize=10)
ax3.set_ylim(0, 1.1)
ax3.legend(fontsize=10)
ax3.grid(axis="y", alpha=0.3)

# 4. Category Winners (Pie Chart - who wins most often)
ax4 = plt.subplot(2, 3, 4)
spec_wins = sum(1 for i in range(len(categories)) if spec_scores[i] >= max(notebooklm_scores[i], rag_scores[i]))
notebooklm_wins = sum(1 for i in range(len(categories)) if notebooklm_scores[i] > spec_scores[i] and notebooklm_scores[i] >= rag_scores[i])
rag_wins = sum(1 for i in range(len(categories)) if rag_scores[i] > spec_scores[i] and rag_scores[i] > notebooklm_scores[i])
ties = len(categories) - spec_wins - notebooklm_wins - rag_wins

sizes = [spec_wins, notebooklm_wins, rag_wins, ties]
labels = [f"Specialized\n({spec_wins})", f"NotebookLM\n({notebooklm_wins})", f"RAG\n({rag_wins})", f"Tied\n({ties})"]
colors_pie = ["#2ecc71", "#3498db", "#e74c3c", "#95a5a6"]

wedges, texts, autotexts = ax4.pie(sizes, labels=labels, colors=colors_pie, autopct="%1.0f%%",
                                     startangle=90, textprops={"fontsize": 11, "fontweight": "bold"})
ax4.set_title("Category Wins", fontsize=14, fontweight="bold")

# 5. Detailed Ranking Table
ax5 = plt.subplot(2, 3, 5)
ax5.axis("off")

table_data = [["Category", "Specialized", "NotebookLM", "RAG", "Winner"]]
for i, cat in enumerate(categories):
    s_score = spec_scores[i]
    n_score = notebooklm_scores[i]
    r_score = rag_scores[i]

    max_score = max(s_score, n_score, r_score)
    if s_score == max_score:
        winner = "S"
    elif n_score == max_score:
        winner = "N"
    elif r_score == max_score:
        winner = "R"
    else:
        winner = "Tie"

    table_data.append([
        cat.split(" ")[0],
        f"{s_score:.2f}",
        f"{n_score:.2f}",
        f"{r_score:.2f}",
        winner
    ])

table = ax5.table(cellText=table_data, cellLoc="center", loc="center",
                  colWidths=[0.25, 0.18, 0.18, 0.18, 0.15])
table.auto_set_font_size(False)
table.set_fontsize(9)
table.scale(1, 2)

# Style header row
for i in range(5):
    table[(0, i)].set_facecolor("#34495e")
    table[(0, i)].set_text_props(weight="bold", color="white")

# Alternate row colors
for i in range(1, len(table_data)):
    for j in range(5):
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

Leader: {'Specialized' if spec_mean > max(notebooklm_mean, rag_mean) else ('NotebookLM' if notebooklm_mean > rag_mean else 'General RAG')} +

Overall Scores:
  Specialized: {spec_mean:.3f}
  NotebookLM: {notebooklm_mean:.3f}
  General RAG: {rag_mean:.3f}

Correct Answers:
  Specialized: {spec_correct}/{total}
  NotebookLM: {notebooklm_correct}/{total}
  General RAG: {rag_correct}/{total}

Partial Correct:
  Specialized: {spec_partial}
  NotebookLM: {notebooklm_partial}
  General RAG: {rag_partial}

Category Winners:
  Specialized: {spec_wins}
  NotebookLM: {notebooklm_wins}
  RAG: {rag_wins}
  Tied: {ties}

Margin Analysis:
  Spec vs NLM: +{spec_mean - notebooklm_mean:.3f}
  Spec vs RAG: +{spec_mean - rag_mean:.3f}
  NLM vs RAG: +{notebooklm_mean - rag_mean:+.3f}
"""

ax6.text(0.05, 0.95, summary_text, transform=ax6.transAxes,
         fontsize=10, verticalalignment="top", fontfamily="monospace",
         bbox=dict(boxstyle="round", facecolor="#ecf0f1", alpha=0.8, pad=1))

plt.tight_layout()
plt.savefig(benchmark_root / "results" / "three_way_comparison.png", dpi=300, bbox_inches="tight")
print(f"[OK] Saved: {benchmark_root / 'results' / 'three_way_comparison.png'}")

# Also save category comparison detail
fig2, ax = plt.subplots(figsize=(14, 6))
x = np.arange(len(categories))
width = 0.25

bars1 = ax.bar(x - width, spec_scores, width, label="Specialized", color="#2ecc71", alpha=0.8, edgecolor="black", linewidth=1.5)
bars2 = ax.bar(x, notebooklm_scores, width, label="NotebookLM", color="#3498db", alpha=0.8, edgecolor="black", linewidth=1.5)
bars3 = ax.bar(x + width, rag_scores, width, label="General RAG", color="#e74c3c", alpha=0.8, edgecolor="black", linewidth=1.5)

ax.set_ylabel("Mean Score", fontsize=14, fontweight="bold")
ax.set_xlabel("Category", fontsize=14, fontweight="bold")
ax.set_title("Three-Way Comparison: Category-by-Category", fontsize=16, fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(categories, rotation=45, ha="right", fontsize=12)
ax.set_ylim(0, 1.1)
ax.legend(fontsize=12, loc="upper right")
ax.grid(axis="y", alpha=0.3, linestyle="--")

# Add value labels on bars
for bars in [bars1, bars2, bars3]:
    for bar in bars:
        height = bar.get_height()
        if height > 0:
            ax.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.2f}', ha='center', va='bottom', fontsize=9, fontweight="bold")

plt.tight_layout()
plt.savefig(benchmark_root / "results" / "three_way_category_detail.png", dpi=300, bbox_inches="tight")
print(f"[OK] Saved: {benchmark_root / 'results' / 'three_way_category_detail.png'}")

print("\nVisualization complete!")
print(f"Open the PNG files in benchmark/results/ to view the charts")
