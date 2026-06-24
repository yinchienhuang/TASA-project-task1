"""
Shared MHTML file reader for multiple modules.
Extracts plain text from .mhtml files.
"""
import email
import pathlib
import re
from pathlib import Path
from bs4 import BeautifulSoup


def _is_garbage_text(text: str) -> bool:
    """Check if a line is garbage (URL, timestamp, etc) and should be filtered."""
    # URLs
    if text.startswith("http://") or text.startswith("https://"):
        return True
    if "URL:" in text and ("http" in text or "amazonaws" in text):
        return True

    # Pure timestamps (ISO 8601 format)
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', text.strip()):
        return True

    # Pure date/time lines without other content
    if re.match(r'^\d{1,2}(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)', text, re.IGNORECASE):
        # Check if it's just a date with optional time, no other content
        if len(text.split()) <= 3:
            return True

    return False


def read_mhtml(path: str | Path) -> str:
    """Extract plain text from a .mhtml file on disk.

    Args:
        path: Absolute or relative path to the .mhtml file

    Returns:
        Plain text content (up to 40,000 characters), filtered for garbage
    """
    path = Path(path)
    msg = email.message_from_bytes(path.read_bytes())
    html = ""
    for part in msg.walk():
        ct = part.get_content_type()
        if ct in ("text/html", "text/plain"):
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ct == "text/html":
                html = decoded
                break
            elif not html:
                html = decoded
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.find("body") or soup

    # Collect text from semantic tags first (high signal)
    seen_texts: set[str] = set()
    parts: list[str] = []

    for tag in body.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "pre", "blockquote"]):
        t = tag.get_text(separator=" ", strip=True)
        if len(t) > 20 and t not in seen_texts and not _is_garbage_text(t):
            parts.append(t)
            seen_texts.add(t)

    # Also scan <div> elements that contain substantive text but are NOT already
    # covered by a child <p>/<td>/etc. JCO reports often wrap narrative in bare divs.
    for div in body.find_all("div"):
        # Skip if this div contains any block-level child already extracted
        if div.find(["p", "li", "table", "h1", "h2", "h3", "h4", "pre", "blockquote"]):
            continue
        t = div.get_text(separator=" ", strip=True)
        # Higher threshold for divs to filter out navigation/button labels
        if len(t) > 60 and t not in seen_texts and not _is_garbage_text(t):
            parts.append(t)
            seen_texts.add(t)

    return "\n\n".join(parts)[:40000]
