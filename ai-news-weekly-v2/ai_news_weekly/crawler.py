import re
from pathlib import Path
from typing import Dict, List, Optional

from .utils import absolute_aibase_url, fetch_text, unique_preserve_order, write_json


LIST_URL = "https://www.aibase.com/zh/news"


def collect_news_ids(list_url: str = LIST_URL, max_items: int = 30) -> List[str]:
    html = fetch_text(list_url)
    ids = re.findall(r'(?:href=\\?"|href=")?/news/(\d+)', html)
    if not ids:
        ids = re.findall(r'"Id"\s*:\s*(\d+)', html)
    return unique_preserve_order(ids)[:max_items]


def crawl_detail_pages(
    max_items: int,
    raw_dir: Path,
    extra_urls: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        ids = collect_news_ids(max_items=max_items)
        urls = [f"https://www.aibase.com/zh/news/{news_id}" for news_id in ids]
        for url in extra_urls or []:
            urls.append(absolute_aibase_url(url))
        urls = unique_preserve_order([u for u in urls if u])
    except Exception:
        cached_index = raw_dir / "crawl_index.json"
        if cached_index.exists():
            return [
                {"source_id": str(item["source_id"]), "url": str(item["url"]), "raw_path": str(item["raw_path"])}
                for item in __import__("json").loads(cached_index.read_text(encoding="utf-8"))
            ]
        raise

    results: List[Dict[str, str]] = []
    for url in urls:
        news_id = url.rstrip("/").split("/")[-1]
        raw_path = raw_dir / f"{news_id}.html"
        try:
            html = fetch_text(url)
            raw_path.write_text(html, encoding="utf-8")
        except Exception:
            if raw_path.exists():
                html = raw_path.read_text(encoding="utf-8")
            else:
                raise
        results.append({"source_id": news_id, "url": url, "raw_path": str(raw_path)})

    write_json(raw_dir / "crawl_index.json", results)
    return results
