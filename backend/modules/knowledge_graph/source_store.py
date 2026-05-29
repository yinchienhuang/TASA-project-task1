"""
SourceStore: persists raw source documents (news articles, uploaded reports).
"""
import json
import pathlib
from datetime import datetime, timezone

SOURCES_DIR = pathlib.Path(__file__).parents[3] / "data" / "sources"
INDEX_FILE = SOURCES_DIR / "index.json"
DOCS_DIR = SOURCES_DIR / "docs"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_index() -> dict:
    if not INDEX_FILE.exists():
        return {}
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(index: dict) -> None:
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def source_exists(source_id: str) -> bool:
    return source_id in _load_index()


def save_source(source_id: str, metadata: dict, content: dict | str) -> None:
    """Persist source to index + docs file."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    index = _load_index()
    # Determine file extension
    if isinstance(content, str):
        ext = ".txt"
        doc_file = DOCS_DIR / f"{source_id}{ext}"
        with open(doc_file, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        ext = ".json"
        doc_file = DOCS_DIR / f"{source_id}{ext}"
        with open(doc_file, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)

    index[source_id] = {
        "source_id": source_id,
        "file": f"docs/{source_id}{ext}",
        "ingested_at": _now(),
        **metadata,
    }
    _save_index(index)


def get_source(source_id: str) -> dict | None:
    """Return full content dict (or text wrapped in dict) for a source."""
    index = _load_index()
    entry = index.get(source_id)
    if not entry:
        return None
    doc_file = SOURCES_DIR / entry["file"]
    if not doc_file.exists():
        return entry  # return metadata only if file missing
    if doc_file.suffix == ".json":
        with open(doc_file, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        with open(doc_file, "r", encoding="utf-8") as f:
            return {"source_id": source_id, "text": f.read(), **entry}


def get_all_sources() -> list[dict]:
    return list(_load_index().values())
