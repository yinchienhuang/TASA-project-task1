"""
PDF parser using PyMuPDF (fitz). Extracts text and tables as Markdown.
"""
from typing import Any


def extract_text(pdf_bytes: bytes) -> dict[str, Any]:
    """
    Extract text from PDF bytes.
    Returns {"text": str, "scanned_pages": [int], "figure_count": int, "metadata": dict}.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {"text": "", "scanned_pages": [], "figure_count": 0, "metadata": {}, "error": "PyMuPDF not installed"}

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    metadata = extract_metadata_from_doc(doc)
    all_text_parts = []
    scanned_pages = []
    figure_count = 0

    for page_num, page in enumerate(doc, start=1):
        page_text_parts = []

        # Get all blocks sorted by vertical position
        blocks = page.get_text("blocks")
        blocks.sort(key=lambda b: (b[1], b[0]))  # sort by y then x

        # Try to detect and extract tables
        table_rects = set()
        try:
            tables = page.find_tables()
            for t_idx, table in enumerate(tables.tables, start=1):
                table_md = _table_to_markdown(table)
                if table_md:
                    page_text_parts.append(f"\n[Table {t_idx} on page {page_num}]\n{table_md}\n")
                    for cell in table.cells:
                        if cell:
                            table_rects.add((round(cell.x0), round(cell.y0), round(cell.x1), round(cell.y1)))
        except Exception:
            pass

        # Add non-table text blocks
        for block in blocks:
            if block[6] == 0:  # text block
                block_text = block[4].strip()
                if block_text:
                    page_text_parts.append(block_text)
            elif block[6] == 1:  # image block
                figure_count += 1
                page_text_parts.append(f"[Figure {figure_count}: image on page {page_num} — content not extractable]")

        page_content = "\n".join(page_text_parts).strip()
        if len(page_content) < 10:
            scanned_pages.append(page_num)
            page_content = f"[Page {page_num}: appears to be scanned/image-only — text not extractable]"

        all_text_parts.append(page_content)

    doc.close()
    full_text = "\n\n---\n\n".join(all_text_parts)
    return {
        "text": full_text,
        "scanned_pages": scanned_pages,
        "figure_count": figure_count,
        "metadata": metadata,
    }


def extract_metadata(pdf_bytes: bytes) -> dict:
    try:
        import fitz
    except ImportError:
        return {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    meta = extract_metadata_from_doc(doc)
    doc.close()
    return meta


def extract_metadata_from_doc(doc) -> dict:
    raw = doc.metadata or {}
    return {
        "title": raw.get("title", ""),
        "author": raw.get("author", ""),
        "creation_date": raw.get("creationDate", ""),
        "subject": raw.get("subject", ""),
    }


def _table_to_markdown(table) -> str:
    """Convert a PyMuPDF table object to a Markdown table string."""
    try:
        rows = table.extract()
        if not rows:
            return ""
        header = rows[0]
        lines = []
        lines.append("| " + " | ".join(str(c or "").strip() for c in header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(str(c or "").strip() for c in row) + " |")
        return "\n".join(lines)
    except Exception:
        return ""
