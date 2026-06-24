"""Test Q&A on main system (not benchmark)."""
import asyncio
import sys
from pathlib import Path

backend_root = Path("backend")
sys.path.insert(0, str(backend_root))

async def test():
    from modules.analysis.qa_engine import run_qa
    
    question = "How many total maneuver events appear across all reports?"
    
    print(f"Question: {question}")
    print(f"\nRunning on MAIN SYSTEM data (not benchmark)...")
    
    result = await run_qa(question)
    answer = result.get("answer", "")
    iterations = result.get("iterations", 0)
    
    print(f"\nAnswer:\n{answer}")
    print(f"\nIterations: {iterations}")

asyncio.run(test())
