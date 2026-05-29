"""
Wikipedia API routes: search, page fetch (with infobox), and KG ingest.
Uses only stdlib HTTP (urllib) — no new dependencies.
"""
import hashlib
import json
import re
import urllib.parse
import urllib.request
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.routes_kg import _run_ingest

router = APIRouter(prefix="/api/wiki", tags=["wikipedia"])

_UA = "TASA-KG-Bot/1.0 (space-situational-awareness)"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Wikipedia API error: {e}")


def _parse_infobox(wikitext: str) -> dict[str, str]:
    """Extract key-value pairs from the first {{Infobox ...}} block in wikitext."""
    # Find the opening of the first infobox
    m = re.search(r'\{\{[Ii]nfobox[^\|{]*\|', wikitext)
    if not m:
        return {}

    # Walk forward tracking brace depth to find the matching }}
    start = m.start()
    depth = 0
    end = start
    i = start
    while i < len(wikitext):
        if wikitext[i:i+2] == '{{':
            depth += 1
            i += 2
        elif wikitext[i:i+2] == '}}':
            depth -= 1
            i += 2
            if depth == 0:
                end = i
                break
        else:
            i += 1

    block = wikitext[start:end]

    result: dict[str, str] = {}
    # Split on newline-pipe pairs — each is one field
    for part in re.split(r'\n\s*\|', block)[1:]:  # skip first segment (infobox type name)
        if '=' not in part:
            continue
        key, _, val = part.partition('=')
        key = key.strip()
        if not key:
            continue

        # Strip wikitext markup from value
        val = re.sub(r'\[\[(?:[^\|\]]*\|)?([^\]]*)\]\]', r'\1', val)   # [[Link|text]] → text
        val = re.sub(r'\{\{[Cc]onvert\|([^|]+)\|[^}]*\}\}', r'\1', val) # {{convert|550|km}} → 550
        val = re.sub(r'\{\{[Ss]tart date[^}]*\|(\d{4})\|(\d+)\|(\d+)[^}]*\}\}', r'\1-\2-\3', val)  # dates
        val = re.sub(r'\{\{[^}]*\}\}', '', val)                          # remaining {{templates}}
        val = re.sub(r'<ref[^>]*>.*?</ref>', '', val, flags=re.DOTALL)   # <ref> tags
        val = re.sub(r'<!--.*?-->', '', val, flags=re.DOTALL)            # HTML comments
        val = re.sub(r'<[^>]+>', '', val)                                 # remaining HTML tags
        val = re.sub(r'\s+', ' ', val).strip()

        if key and val:
            result[key] = val

    return result


def _fetch_page_data(title: str, lang: str) -> dict:
    """Fetch summary, infobox, and categories for a Wikipedia article."""
    encoded = urllib.parse.quote(title, safe='')

    # 1. REST summary — clean intro text + metadata
    summary_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    try:
        summary = _get(summary_url)
    except HTTPException:
        raise HTTPException(status_code=404, detail=f"Wikipedia page not found: {title!r} (lang={lang})")

    if not isinstance(summary, dict):
        raise HTTPException(status_code=404, detail="Unexpected Wikipedia API response")

    page_title   = summary.get("title", title)
    description  = summary.get("description", "")
    extract      = summary.get("extract", "")
    last_mod     = (summary.get("timestamp") or "")[:10]
    wikidata_id  = summary.get("wikibase_item", "")
    page_url     = (summary.get("content_urls") or {}).get("desktop", {}).get("page", "")
    page_type    = summary.get("type", "")  # "disambiguation", "standard", etc.

    if not page_url:
        page_url = f"https://{lang}.wikipedia.org/wiki/{encoded}"

    # 2. Wikitext — for infobox extraction
    wikitext_url = (
        f"https://{lang}.wikipedia.org/w/api.php"
        f"?action=query&titles={encoded}&prop=revisions&rvprop=content"
        f"&rvslots=main&format=json&formatversion=2"
    )
    infobox: dict[str, str] = {}
    try:
        wt_data = _get(wikitext_url)
        pages = (wt_data.get("query") or {}).get("pages") or []
        if pages:
            page = pages[0]
            if page.get("pageid", -1) != -1:
                revs = page.get("revisions") or []
                if revs:
                    wikitext = (revs[0].get("slots") or {}).get("main", {}).get("content", "")
                    infobox = _parse_infobox(wikitext)
    except HTTPException:
        pass  # infobox is optional — don't fail the whole fetch

    # 3. Categories
    cats_url = (
        f"https://{lang}.wikipedia.org/w/api.php"
        f"?action=query&titles={encoded}&prop=categories"
        f"&format=json&formatversion=2&cllimit=20&clshow=!hidden"
    )
    categories: list[str] = []
    try:
        cats_data = _get(cats_url)
        pages = (cats_data.get("query") or {}).get("pages") or []
        if pages:
            raw_cats = pages[0].get("categories") or []
            categories = [
                re.sub(r'^[Cc]ategory:', '', c["title"]).strip()
                for c in raw_cats
            ]
    except HTTPException:
        pass  # categories are optional

    return {
        "title":        page_title,
        "lang":         lang,
        "page_type":    page_type,
        "description":  description,
        "extract":      extract,
        "infobox":      infobox,
        "categories":   categories,
        "wikidata_id":  wikidata_id,
        "last_modified": last_mod,
        "url":          page_url,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/search")
def wiki_search(
    q: str = Query(..., min_length=1),
    lang: str = Query("en"),
    limit: int = Query(10, ge=1, le=50),
) -> list[dict]:
    """Search Wikipedia in any language. Returns [{title, description, url}]."""
    url = (
        f"https://{lang}.wikipedia.org/w/api.php"
        f"?action=opensearch&search={urllib.parse.quote(q)}"
        f"&limit={limit}&format=json&namespace=0"
    )
    data = _get(url)
    if not isinstance(data, list) or len(data) < 4:
        return []
    titles, descs, urls = data[1], data[2], data[3]
    return [{"title": t, "description": d, "url": u} for t, d, u in zip(titles, descs, urls)]


@router.get("/page")
def wiki_page(
    title: str = Query(...),
    lang: str = Query("en"),
) -> dict:
    """Fetch structured page data: summary, infobox (key-value), categories, metadata."""
    return _fetch_page_data(title, lang)


class WikiIngestRequest(BaseModel):
    title: str
    lang: str = "en"
    mode: Literal["review", "auto"] = "review"


@router.post("/ingest")
async def wiki_ingest(req: WikiIngestRequest) -> dict:
    """Fetch a Wikipedia page and push it through the KG ingest pipeline."""
    page = _fetch_page_data(req.title, req.lang)

    # Build text payload — infobox first (structured), then prose
    lines: list[str] = []
    if page["infobox"]:
        lines.append("=== Infobox ===")
        for k, v in page["infobox"].items():
            lines.append(f"{k}: {v}")
        lines.append("")
    if page["description"]:
        lines.append(f"Description: {page['description']}")
        lines.append("")
    if page["extract"]:
        lines.append("=== Article Extract ===")
        lines.append(page["extract"])
    if page["categories"]:
        lines.append("")
        lines.append("Categories: " + ", ".join(page["categories"]))

    text = "\n".join(lines)

    url = page["url"]
    source_id = "sha_" + hashlib.sha256(url.encode()).hexdigest()[:16]
    source = {
        "type": "wikipedia",
        "title": page["title"],
        "url": url,
        "lang": req.lang,
        "date": page["last_modified"],
        "news_site": f"{req.lang}.wikipedia.org",
        "categories": page["categories"],
        "wikidata_id": page["wikidata_id"],
    }

    return await _run_ingest(text, source, source_id, req.mode)