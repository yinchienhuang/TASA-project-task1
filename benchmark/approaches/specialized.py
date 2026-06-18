"""
Specialized approach: Domain-aware extraction + Q&A using the system's existing tools.

Uses:
- jco_extractor.py for event extraction (schema-guided)
- qa_engine.py for multi-tool Q&A
- Benchmark's own event_store (benchmark/data/events.json)
"""
import sys
import json
from pathlib import Path

# Setup path
benchmark_root = Path(__file__).parent.parent
backend_root = benchmark_root.parent / "backend"
sys.path.insert(0, str(backend_root))


async def extract_events_from_reports(reports):
    """Extract events from all reports using specialized jco_extractor."""
    from modules.events.jco_extractor import extract_events_from_jco
    from modules.knowledge_graph.mhtml_reader import read_mhtml

    all_events = []

    for report_path in reports:
        try:
            text = read_mhtml(report_path)
            if not text:
                continue

            events = await extract_events_from_jco(
                text,
                {"title": report_path.name, "source_id": str(report_path)}
            )
            if events:
                all_events.extend(events)
        except Exception as e:
            print(f"Warning: extraction failed for {report_path.name}: {e}")

    return all_events


async def answer_question(question, benchmark_events, kg_graph):
    """Answer a question using specialized Q&A engine with multi-tool calling."""
    from modules.analysis.qa_engine import run_qa
    from modules.events.event_store import EventStore
    from modules.knowledge_graph.kg_store import kg_store

    # Create a temporary event store with benchmark events
    temp_store = EventStore()
    for event in benchmark_events:
        temp_store.add_event(event)

    # Monkey-patch the global event_store for this call
    import modules.events.event_store as event_store_module
    original_store = event_store_module.event_store
    event_store_module.event_store = temp_store

    # Monkey-patch the KG store to use benchmark's KG graph
    original_kg_nodes = kg_store.nodes.copy() if hasattr(kg_store, 'nodes') else {}
    original_kg_edges = kg_store.edges.copy() if hasattr(kg_store, 'edges') else []

    # Load benchmark KG data
    if kg_graph and isinstance(kg_graph, dict):
        kg_store.nodes = kg_graph.get("nodes", {})
        kg_store.edges = kg_graph.get("edges", [])

    try:
        # Use the Q&A engine with its tools (now with both event_store and KG patched)
        result = await run_qa(question)
        answer = result.get("answer", "")
        return answer if isinstance(answer, str) else str(answer)
    finally:
        # Restore original stores
        event_store_module.event_store = original_store
        kg_store.nodes = original_kg_nodes
        kg_store.edges = original_kg_edges


def load_benchmark_events():
    """Load pre-extracted events from benchmark/data/events.json."""
    events_file = benchmark_root / "data" / "events.json"
    if not events_file.exists():
        print(f"Warning: {events_file} not found. Have you run setup.py?")
        return []

    with open(events_file, encoding='utf-8') as f:
        data = json.load(f)
    return data.get("events", [])


def load_kg_graph():
    """Load KG graph for multi-hop reasoning."""
    kg_file = benchmark_root.parent / "data" / "kg" / "graph.json"
    if not kg_file.exists():
        print(f"Warning: {kg_file} not found")
        return {}

    with open(kg_file, encoding='utf-8') as f:
        return json.load(f)
