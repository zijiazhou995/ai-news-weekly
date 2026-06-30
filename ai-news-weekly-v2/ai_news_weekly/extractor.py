import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Article
from .utils import (
    absolute_aibase_url,
    extract_meta,
    html_to_paragraphs,
    normalize_space,
    parse_date,
)


def _decode_next_text(html_text: str) -> str:
    chunks: List[str] = []
    for match in re.finditer(r'self\.__next_f\.push\(\[1,"((?:\\.|[^"\\])*)"\]\)', html_text):
        try:
            chunks.append(json.loads('"' + match.group(1) + '"'))
        except json.JSONDecodeError:
            continue
    return "\n".join(chunks)


def _json_string_value(text: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', text)
    if not match:
        return ""
    try:
        return json.loads('"' + match.group(1) + '"')
    except json.JSONDecodeError:
        return match.group(1)


def _json_number_value(text: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(\d+)', text)
    return match.group(1) if match else ""


def _extract_summary_fragment(html_text: str) -> str:
    marker = '"summary"'
    idx = html_text.find(marker)
    if idx < 0:
        return ""
    value = _json_string_value(html_text[idx : idx + 60000], "summary")
    if value.startswith("$"):
        ref = value[1:]
        ref_match = re.search(rf'\n{re.escape(ref)}:T[0-9a-f]+,\n(.*?)(?:\n\d+:|\Z)', html_text, re.S)
        if ref_match:
            return ref_match.group(1)
    return value


def extract_article(raw_path: Path, fallback_url: str = "") -> Optional[Article]:
    html_text = raw_path.read_text(encoding="utf-8", errors="replace")
    next_text = _decode_next_text(html_text)
    data_text = next_text or html_text

    title = (
        extract_meta(html_text, "og:title")
        or _json_string_value(data_text, "title")
        or _title_tag(html_text)
    )
    description = extract_meta(html_text, "description") or _json_string_value(
        data_text, "description"
    )
    source_id = _json_number_value(data_text, "Id") or raw_path.stem
    url = absolute_aibase_url(
        extract_meta(html_text, "og:url") or fallback_url or f"/zh/news/{source_id}"
    )
    addtime = _json_string_value(data_text, "addtime") or _json_string_value(
        data_text, "updtime"
    )
    parsed_date = parse_date(addtime)
    date = parsed_date.isoformat() if parsed_date else addtime[:10]

    summary_fragment = _extract_summary_fragment(data_text)
    paragraphs = html_to_paragraphs(summary_fragment)
    lead = paragraphs[0] if paragraphs else normalize_space(description)
    first_paragraph = paragraphs[1] if len(paragraphs) > 1 else lead

    tags = _parse_tags(_json_string_value(html_text, "tags"))
    if not title or not date:
        return None

    return Article(
        source="AIbase",
        source_id=source_id,
        url=url,
        title=normalize_space(title),
        date=date,
        lead=normalize_space(lead),
        first_paragraph=normalize_space(first_paragraph),
        description=normalize_space(description),
        tags=tags,
        raw={"raw_path": str(raw_path), "addtime": addtime},
    )


def extract_from_crawl_index(index: List[Dict[str, str]]) -> List[Article]:
    articles: List[Article] = []
    for item in index:
        article = extract_article(Path(item["raw_path"]), fallback_url=item.get("url", ""))
        if article:
            articles.append(article)
    return articles


def _title_tag(html_text: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html_text, re.S | re.I)
    return normalize_space(match.group(1)) if match else ""


def _parse_tags(value: str) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [normalize_space(str(v)) for v in parsed if normalize_space(str(v))]
    except json.JSONDecodeError:
        pass
    return [part.strip() for part in re.split(r"[,，]", value) if part.strip()]
