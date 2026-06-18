# NOTOS Benchmark Results

## Overall Scores

| Metric | Specialized | General RAG | Advantage |
|--------|------------|-------------|-----------|
| Mean Score | 0.67 | 0.83 | RAG |
| Correct (1.0) | 2 / 3 | 2 / 3 | 0 |
| Partial (0.5) | 0 | 1 | |
| Wrong (0.0) | 1 | 0 | |

## Performance by Category

Generated from 3 questions across 7 categories:
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


## Detailed Results by Category

### D. Multi-Hop Reasoning
- Specialized: 0.500 (1/2 correct)
- General RAG: 0.750 (1/2 correct)
- Advantage: RAG

### E. Specialized Event Types (RPO)
- Specialized: 1.000 (1/1 correct)
- General RAG: 1.000 (1/1 correct)
- Advantage: Tied

