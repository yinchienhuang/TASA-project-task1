#!/usr/bin/env python3
"""
Benchmark setup: Extract all 27 NOTOS/JCO reports using specialized system,
and build RAG corpus from the same reports.

Usage:
    python benchmark/setup.py

Output:
    benchmark/data/events.json          - All extracted events (27 reports)
    benchmark/data/rag_corpus/*.npy     - Embedding vectors
    benchmark/data/rag_corpus/metadata.json  - Chunk metadata
"""
import asyncio
import json
import sys
import os
from pathlib import Path
import numpy as np

# Load environment from backend/.env
from dotenv import load_dotenv
backend_env = Path(__file__).parent.parent / "backend" / ".env"
if backend_env.exists():
    load_dotenv(backend_env)

# Add backend to path so we can import its modules
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from modules.events.jco_extractor import extract_events_from_jco
from modules.knowledge_graph.mhtml_reader import read_mhtml

try:
    from openai import OpenAI
except ImportError:
    print("Error: openai not installed. Please run: pip install openai")
    sys.exit(1)


def setup_directories():
    """Create benchmark data directories."""
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    rag_corpus_dir = data_dir / "rag_corpus"
    rag_corpus_dir.mkdir(parents=True, exist_ok=True)

    return data_dir, rag_corpus_dir


def find_mhtml_reports():
    """Find all MHTML files in data/JCO report/."""
    project_root = Path(__file__).parent.parent
    report_dir = project_root / "data" / "JCO report"

    if not report_dir.exists():
        print(f"Error: Report directory not found: {report_dir}")
        sys.exit(1)

    reports = sorted(report_dir.glob("*.mhtml"))
    print(f"Found {len(reports)} MHTML reports")
    return reports


async def extract_all_events(reports):
    """Extract events from all reports using specialized system."""
    print(f"\n=== Extracting events from {len(reports)} reports ===")

    all_events = []

    for i, report_path in enumerate(reports, 1):
        try:
            text = read_mhtml(report_path)
            if not text:
                print(f"  [{i}/{len(reports)}] {report_path.name}: No text extracted")
                continue

            # Extract events using specialized system
            events = await extract_events_from_jco(
                text,
                {"title": report_path.name, "source_id": str(report_path)}
            )

            if events:
                all_events.extend(events)
                print(f"  [{i}/{len(reports)}] {report_path.name}: {len(events)} events")
            else:
                print(f"  [{i}/{len(reports)}] {report_path.name}: 0 events")

        except Exception as e:
            print(f"  [{i}/{len(reports)}] {report_path.name}: ERROR - {e}")

    print(f"\nTotal events extracted: {len(all_events)}")
    return all_events


def build_rag_corpus(reports, rag_corpus_dir):
    """Build RAG corpus by chunking and embedding all reports.

    Note: RAG corpus building is optional. If it fails, we continue with events extraction.
    """
    print(f"\n=== Building RAG corpus with {len(reports)} reports ===")

    try:
        client = OpenAI()
    except Exception as e:
        print(f"Warning: Cannot initialize OpenAI client: {e}")
        print("Skipping RAG corpus build (optional for benchmark)")
        return

    all_chunks = []
    chunk_metadata = []
    chunk_count = 0

    for i, report_path in enumerate(reports, 1):
        try:
            text = read_mhtml(report_path)
            if not text:
                print(f"  [{i}/{len(reports)}] {report_path.name}: No text")
                continue

            # Simple chunking: split on \n\n (paragraph breaks), with 400-token target
            # Rough estimate: 1 token ≈ 4 characters
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            chunks = []
            current_chunk = []
            current_size = 0

            for para in paragraphs:
                para_size = len(para) // 4  # Rough token count

                if current_size + para_size > 400 and current_chunk:
                    # Save current chunk and start new
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = [para]
                    current_size = para_size
                else:
                    current_chunk.append(para)
                    current_size += para_size

            if current_chunk:
                chunks.append("\n\n".join(current_chunk))

            # Embed chunks (with error recovery)
            print(f"  [{i}/{len(reports)}] {report_path.name}: {len(chunks)} chunks... ", end="", flush=True)

            for j, chunk in enumerate(chunks):
                try:
                    response = client.embeddings.create(
                        model="text-embedding-3-small",
                        input=chunk,
                        timeout=30
                    )
                    embedding = response.data[0].embedding
                    all_chunks.append(embedding)
                    chunk_metadata.append({
                        "report": report_path.name,
                        "chunk_id": j,
                        "text_preview": chunk[:100].replace("\n", " "),
                    })
                    chunk_count += 1
                except Exception as e:
                    print(f"[chunk {j} error: {str(e)[:30]}]", end="", flush=True)

            print("done")

        except Exception as e:
            print(f"  [{i}/{len(reports)}] {report_path.name}: ERROR - {e}")

    if all_chunks:
        # Save embeddings and metadata
        try:
            embeddings_array = np.array(all_chunks, dtype=np.float32)
            np.save(str(rag_corpus_dir / "embeddings.npy"), embeddings_array)

            with open(rag_corpus_dir / "metadata.json", "w") as f:
                json.dump(chunk_metadata, f, indent=2)

            print(f"\nRAG corpus saved: {chunk_count} chunks")
            print(f"  Embeddings: {rag_corpus_dir / 'embeddings.npy'}")
            print(f"  Metadata:   {rag_corpus_dir / 'metadata.json'}")
        except Exception as e:
            print(f"\nWarning: Failed to save RAG corpus: {e}")
    else:
        print("Warning: No chunks embedded; RAG corpus not built (optional)")


async def main():
    """Main setup routine."""
    print("=" * 60)
    print("NOTOS Benchmark Setup")
    print("=" * 60)

    # Setup
    data_dir, rag_corpus_dir = setup_directories()
    reports = find_mhtml_reports()

    # Extract events
    events = await extract_all_events(reports)

    # Save events
    events_file = data_dir / "events.json"
    with open(events_file, "w") as f:
        json.dump({"events": events, "count": len(events)}, f, indent=2)
    print(f"\nEvents saved to: {events_file}")

    # Build RAG corpus
    build_rag_corpus(reports, rag_corpus_dir)

    print("\n" + "=" * 60)
    print("Setup complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
