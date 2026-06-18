# NOTOS Benchmark — Specialized System vs General RAG

## Overview

This benchmark compares two approaches to extracting structured information from NOTOS/JCO space intelligence reports:

1. **Specialized System** — Domain-aware GPT-4o extraction with schema guidance (this project's `jco_extractor.py` + `qa_engine.py`)
2. **General RAG** — Generic RAG pipeline with embedding-based retrieval + vanilla LLM (no domain knowledge)

Using **27 NOTOS/JCO MHTML reports** spanning maneuver, photometric change, launch, and RPO (Rendezvous/Proximity Operations) events.

## Directory Structure

```
benchmark/
├── setup.py                 # Extract events from all 27 reports + build RAG corpus
├── build_ground_truth.py    # Generate ground truth using GPT-4o
├── questions.json           # 25 test questions (7 categories)
├── ground_truth.json        # Correct answers (human-reviewed)
├── approaches/
│   ├── specialized.py       # Specialized system wrapper
│   └── general_rag.py       # General RAG approach
├── evaluate.py              # Scoring logic
├── run_benchmark.py         # Main entry point
├── data/
│   ├── events.json          # Extracted events (27 reports)
│   └── rag_corpus/          # Embeddings + metadata
└── results/
    ├── report.json          # Numeric results
    └── report.md            # Human-readable report
```

## Quick Start

### 1. Setup Environment
```bash
cd backend
pip install -r requirements.txt
cd ..
```

### 2. Extract Events & Build RAG Corpus
```bash
python benchmark/setup.py
```

This will:
- Read all 27 `.mhtml` files from `data/JCO report/`
- Extract events using `jco_extractor.py` → `benchmark/data/events.json`
- Chunk and embed all reports with `text-embedding-3-small` → `benchmark/data/rag_corpus/`

### 3. Generate Ground Truth (Manual Review Required)
```bash
python benchmark/build_ground_truth.py
```

This will output `benchmark/ground_truth.json` with GPT-4o annotations.
**Important**: Review and correct these annotations before proceeding (they are the ground truth).

### 4. Run Benchmark
```bash
python benchmark/run_benchmark.py
```

This will:
- Load ground truth and RAG corpus
- Run both approaches on all 25 questions
- Score and generate `benchmark/results/report.md`

### 5. View Results
```bash
cat benchmark/results/report.md
```

## Question Categories

| Category | Count | Failure Mode Demonstrated |
|----------|-------|--------------------------|
| **A. Event Precision** | 5 | Numeric rounding, sign loss |
| **B. Cross-Document Aggregation** | 5 | Cannot aggregate across multiple files |
| **C. Date Format Normalization** | 3 | Fails to normalize `18May2010z` → ISO 8601 |
| **D. Multi-Hop Reasoning** | 4 | Cannot chain KG lookups + orbital computation |
| **E. Specialized Event Types (RPO)** | 3 | Cannot extract novel schema fields |
| **F. I Don't Know (Hallucination)** | 3 | Tendency to fabricate answers |
| **G. Satellite Name Variants** | 2 | Embedding similarity fails on ID vs name |

## Scoring

### Event Extraction (Evaluation Phase)
- **True Positive**: Same `satellite_id` + event within ±5 min + matching `type`
- **Precision / Recall / F1**
- **Field Accuracy**: Within tolerance for numeric fields (±5%)
- **Hallucination Rate**: FP / (TP + FP)

### Q&A (Evaluation Phase)
- **Numeric**: Tolerance-based (±5%)
- **Numeric + Sign**: Sign error → 0 points
- **Datetime**: ISO 8601 correct → 1.0, wrong format → 0.5
- **Free-form**: GPT-4o judge (0 / 0.5 / 1.0)
- **"I Don't Know" questions**: Refusal → 1.0, hallucination → 0

## Expected Results

### Extraction Accuracy
- **Specialized**: F1 > 80% (schema-guided, domain-aware)
- **General RAG**: F1 < 50% (no schema, struggles with numeric fields)

### Q&A Performance
- **Specialized**: Excels at:
  - Cross-document aggregation (visits all events)
  - Multi-hop reasoning (KG integration)
  - Novel event types (RPO) with proper schema
- **General RAG**: Limited to:
  - Top-K chunk retrieval (misses out-of-top-K facts)
  - Single-document questions
  - Generic Q&A without domain knowledge

## Technical Notes

### Shared MHTML Reader
All report reading now uses `backend/modules/knowledge_graph/mhtml_reader.py::read_mhtml()`:
- Parses `.mhtml` as MIME message
- Extracts HTML from message parts
- Cleans noise (scripts, headers, footers)
- Returns first 40,000 characters

### Benchmark Data Isolation
- `benchmark/data/events.json` is **isolated** from main system's `data/events/events.json`
- Allows 27-report extraction without affecting production data
- Q&A tools in specialized approach use benchmark event store

### OpenAI Requirements
- `text-embedding-3-small` for RAG corpus (cheap embeddings)
- `gpt-4o` for LLM-based ground truth and Q&A
- Requires `OPENAI_API_KEY` environment variable

## Troubleshooting

**Q: "Report directory not found"**
- Ensure `data/JCO report/` exists in project root

**Q: "OpenAI API key error"**
- Set `export OPENAI_API_KEY=<your-key>` before running

**Q: "ModuleNotFoundError" when importing backend modules**
- `setup.py` adds backend to sys.path; verify `backend/` directory exists

**Q: Ground truth annotations look incomplete**
- `build_ground_truth.py` uses GPT-4o; review and edit `benchmark/ground_truth.json` before running benchmark

## References

- **Specialized Extractor**: `backend/modules/events/jco_extractor.py`
- **Q&A Engine**: `backend/modules/analysis/qa_engine.py`
- **MHTML Reader**: `backend/modules/knowledge_graph/mhtml_reader.py`
- **Event Store**: `backend/modules/events/event_store.py`
