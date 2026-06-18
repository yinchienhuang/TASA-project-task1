#!/usr/bin/env python3
"""Quick test of event extraction from one report."""
import asyncio
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment
backend_env = Path(__file__).parent.parent / "backend" / ".env"
if backend_env.exists():
    load_dotenv(backend_env)

print(f"OPENAI_API_KEY set: {'OPENAI_API_KEY' in os.environ}")

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from modules.events.jco_extractor import extract_events_from_jco
from modules.knowledge_graph.mhtml_reader import read_mhtml


async def test_one_report():
    """Test extraction on first report."""
    report_dir = Path(__file__).parent.parent / "data" / "JCO report"
    reports = sorted(report_dir.glob("*.mhtml"))

    if not reports:
        print("No reports found!")
        return

    report = reports[0]
    print(f"\nTesting: {report.name}")

    try:
        text = read_mhtml(report)
        print(f"Text length: {len(text)} chars")

        if not text:
            print("No text extracted!")
            return

        print("Calling extract_events_from_jco...")
        events = await extract_events_from_jco(
            text,
            {"title": report.name, "source_id": str(report)}
        )

        print(f"Extracted {len(events)} events")
        if events:
            print(f"First event type: {events[0].get('type')}")
        else:
            print("No events extracted")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_one_report())
