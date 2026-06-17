#!/usr/bin/env python3
"""Semi-automatic weekly AI product/news brief generator.

The tool intentionally uses only Python's standard library so it can run on a
plain macOS install. It collects RSS/Google News candidates, merges manual
items, scores them against the user's editorial rules, and writes a draft that
is ready for human review.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config" / "settings.json"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"
INBOX_FILE = ROOT / "inbox" / "manual_items.jsonl"
PROMPT_FILE = ROOT / "prompts" / "rewrite_prompt.md"
SITE_DIR = ROOT / "site"
SITE_WEEKS_DIR = SITE_DIR / "weeks"
SITE_INDEX_FILE = DATA_DIR / "site_weeks.json"
CHINA_TZ = dt.timezone(dt.timedelta(hours=8))


@dataclass
class FetchResult:
    items: List[Dict[str, Any]]
    errors: List[str]


def now_cn() -> dt.datetime:
    return dt.datetime.now(tz=CHINA_TZ)


def load_settings() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Missing config file: {CONFIG_FILE}")
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    INBOX_FILE.parent.mkdir(exist_ok=True)


def compact_text(value: Optional[str], max_len: Optional[int] = None) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if max_len and len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def find_child(elem: ET.Element, names: Iterable[str]) -> Optional[ET.Element]:
    wanted = set(names)
    for child in list(elem):
        if local_name(child.tag) in wanted:
            return child
    return None


def find_text(elem: ET.Element, names: Iterable[str]) -> str:
    child = find_child(elem, names)
    if child is None:
        return ""
    return "".join(child.itertext()).strip()


def parse_dt(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(CHINA_TZ)
    except (TypeError, ValueError, IndexError):
        pass

    iso_value = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(iso_value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(CHINA_TZ)
    except ValueError:
        return None


def date_cn(value: Optional[str]) -> str:
    parsed = parse_dt(value)
    if parsed:
        return f"{parsed.month}月{parsed.day}日"
    return now_cn().strftime("%-m月%-d日") if sys.platform != "win32" else now_cn().strftime("%#m月%#d日")


def week_key(today: Optional[dt.datetime] = None) -> str:
    current = today or now_cn()
    year, week, _ = current.isocalendar()
    return f"{year}-W{week:02d}"


def week_range(days: int) -> Tuple[dt.datetime, dt.datetime]:
    end = now_cn()
    start = end - dt.timedelta(days=days)
    return start, end


def source_url(source: Dict[str, Any], lookback_days: int) -> str:
    source_type = source.get("type", "rss")
    if source_type == "aibase_news":
        return source.get("url", "https://www.aibase.com/zh/news")
    if source_type == "sogou_news":
        params = {"query": source["query"], "mode": "1"}
        return "https://news.sogou.com/news?" + urllib.parse.urlencode(params)
    if source_type == "so360_news":
        params = {"q": source["query"], "src": "news"}
        return "https://news.so.com/ns?" + urllib.parse.urlencode(params)
    if source_type == "google_news":
        query = source["query"]
        if "when:" not in query:
            query = f"{query} when:{lookback_days}d"
        params = {
            "q": query,
            "hl": source.get("hl", "zh-CN"),
            "gl": source.get("gl", "CN"),
            "ceid": source.get("ceid", "CN:zh-Hans"),
        }
        return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    if source_type == "bing_news":
        query = source["query"]
        params = {
            "q": query,
            "format": "RSS",
            "mkt": source.get("mkt", "zh-CN"),
        }
        host = source.get("host", "cn.bing.com")
        return f"https://{host}/news/search?" + urllib.parse.urlencode(params)
    if source_type == "rss":
        return source["url"]
    raise ValueError(f"Unsupported source type: {source_type}")


def fetch_url(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 weekly-ai-news/1.0 (+local editorial tool)",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return response.read()


def atom_link(item: ET.Element) -> str:
    for child in list(item):
        if local_name(child.tag) != "link":
            continue
        rel = child.attrib.get("rel", "alternate")
        href = child.attrib.get("href", "")
        if href and rel == "alternate":
            return href
    return ""


def parse_feed(raw: bytes, source: Dict[str, Any]) -> List[Dict[str, Any]]:
    root = ET.fromstring(raw)
    feed_items = [elem for elem in root.iter() if local_name(elem.tag) in {"item", "entry"}]
    items: List[Dict[str, Any]] = []
    for elem in feed_items:
        title = compact_text(find_text(elem, ["title"]), 220)
        description = compact_text(find_text(elem, ["description", "summary", "content", "encoded"]), 700)
        link = compact_text(find_text(elem, ["link"]))
        if not link:
            link = atom_link(elem)
        published = compact_text(find_text(elem, ["pubDate", "published", "updated", "dc:date"]))
        if not title and not description:
            continue
        items.append(
            {
                "title": title,
                "summary": description,
                "url": link,
                "published_at": published,
                "source": source.get("name", ""),
                "source_priority": source.get("priority", 0),
                "official_source": bool(source.get("official", False)),
            }
        )
    return items


def clean_html_fragment(value: str, max_len: Optional[int] = None) -> str:
    value = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    value = re.sub(r"<em[^>]*>", "", value, flags=re.I)
    value = re.sub(r"</em>", "", value, flags=re.I)
    return compact_text(value, max_len=max_len)


def absolutize_url(url: str, base: str) -> str:
    url = html.unescape(url or "").strip()
    if not url:
        return ""
    return urllib.parse.urljoin(base, url)


def parse_cn_news_datetime(value: str) -> Tuple[str, str]:
    text = compact_text(value)
    current = now_cn()

    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        parsed = dt.datetime(year, month, day, 12, tzinfo=CHINA_TZ)
        return parsed.isoformat(), f"{month}月{day}日"

    match = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if match:
        month, day = (int(part) for part in match.groups())
        year = current.year
        parsed = dt.datetime(year, month, day, 12, tzinfo=CHINA_TZ)
        if parsed > current + dt.timedelta(days=1):
            parsed = parsed.replace(year=year - 1)
        return parsed.isoformat(), f"{month}月{day}日"

    match = re.search(r"(\d+)\s*天前", text)
    if match:
        parsed = current - dt.timedelta(days=int(match.group(1)))
        return parsed.isoformat(), f"{parsed.month}月{parsed.day}日"

    match = re.search(r"(\d+)\s*小时前", text)
    if match:
        parsed = current - dt.timedelta(hours=int(match.group(1)))
        return parsed.isoformat(), f"{parsed.month}月{parsed.day}日"

    if "分钟前" in text or "刚刚" in text or "今天" in text:
        return current.isoformat(), f"{current.month}月{current.day}日"

    return "", ""


def parse_sogou_news(raw: bytes, source: Dict[str, Any], url: str) -> List[Dict[str, Any]]:
    text = raw.decode("utf-8", "replace")
    blocks = re.findall(r'(<div class="vrwrap".*?)(?=<div class="vrwrap"|\Z)', text, flags=re.S)
    items: List[Dict[str, Any]] = []
    for block in blocks:
        title_match = re.search(r'<h3[^>]*class="[^"]*vr-title[^"]*"[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.S | re.I)
        if not title_match:
            continue
        item_url = absolutize_url(title_match.group(1), url)
        title = clean_html_fragment(title_match.group(2), 120)

        summary_match = re.search(r'<p[^>]*class="[^"]*(?:star-wiki|str_info|ft|summary)[^"]*"[^>]*>(.*?)</p>', block, flags=re.S | re.I)
        summary = clean_html_fragment(summary_match.group(1), 350) if summary_match else ""
        if title in {"快讯", "资讯", "新闻"} and summary:
            title = first_sentence(summary, 80)

        source_name = source.get("name", "搜狗新闻")
        date_text = ""
        from_match = re.search(r'<p[^>]*class="[^"]*news-from[^"]*"[^>]*>(.*?)</p>', block, flags=re.S | re.I)
        if from_match:
            spans = re.findall(r"<span[^>]*>(.*?)</span>", from_match.group(1), flags=re.S | re.I)
            cleaned_spans = [clean_html_fragment(span, 80) for span in spans if clean_html_fragment(span)]
            if cleaned_spans:
                source_name = cleaned_spans[0]
            if len(cleaned_spans) >= 2:
                date_text = cleaned_spans[1]

        published_at, display_date = parse_cn_news_datetime(date_text or summary)
        if not title or not item_url.startswith("http"):
            continue
        items.append(
            {
                "title": title,
                "summary": summary,
                "url": item_url,
                "published_at": published_at,
                "date": display_date,
                "source": f"{source.get('name', '搜狗新闻')} / {source_name}",
                "source_priority": source.get("priority", 0),
                "official_source": False,
            }
        )
    return items


def parse_so360_news(raw: bytes, source: Dict[str, Any], url: str) -> List[Dict[str, Any]]:
    text = raw.decode("utf-8", "replace")
    blocks = re.findall(r'(<li[^>]+class="[^"]*res-list[^"]*"[^>]*>.*?</li>)', text, flags=re.S | re.I)
    items: List[Dict[str, Any]] = []
    for block in blocks:
        href_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*(?:title="([^"]*)")?[^>]*>', block, flags=re.S | re.I)
        if not href_match:
            continue
        item_url = absolutize_url(href_match.group(1), url)
        title = clean_html_fragment(href_match.group(2) or "", 120)
        if not title:
            title_match = re.search(r"<h3[^>]*>(.*?)</h3>", block, flags=re.S | re.I)
            title = clean_html_fragment(title_match.group(1), 120) if title_match else ""

        summary_match = re.search(r'<p[^>]+class="[^"]*summary[^"]*"[^>]*>(.*?)</p>', block, flags=re.S | re.I)
        summary = clean_html_fragment(summary_match.group(1), 350) if summary_match else ""
        site_match = re.search(r'<cite[^>]*class="[^"]*sitename[^"]*"[^>]*>(.*?)</cite>', block, flags=re.S | re.I)
        site = clean_html_fragment(site_match.group(1), 80) if site_match else ""
        time_match = re.search(r'<span[^>]*class="[^"]*time[^"]*"[^>]*>(.*?)</span>', block, flags=re.S | re.I)
        time_text = clean_html_fragment(time_match.group(1), 80) if time_match else ""
        published_at, display_date = parse_cn_news_datetime(time_text or summary)

        if not title or not item_url.startswith("http"):
            continue
        items.append(
            {
                "title": title,
                "summary": summary,
                "url": item_url,
                "published_at": published_at,
                "date": display_date,
                "source": f"{source.get('name', '360资讯搜索')} / {site or '未知媒体'}",
                "source_priority": source.get("priority", 0),
                "official_source": False,
            }
        )
    return items


def parse_aibase_news(raw: bytes, source: Dict[str, Any], url: str) -> List[Dict[str, Any]]:
    text = raw.decode("utf-8", "replace")
    blocks = re.findall(r'(<a[^>]+href="[^"]*/news/\d+[^"]*"[^>]*>.*?</a>)', text, flags=re.S | re.I)
    items: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    for block in blocks:
        href_match = re.search(r'href="([^"]*/news/\d+[^"]*)"', block, flags=re.S | re.I)
        if not href_match:
            continue
        item_url = absolutize_url(href_match.group(1), url)
        if item_url in seen_urls:
            continue
        seen_urls.add(item_url)

        title_match = re.search(r"<h3[^>]*>(.*?)</h3>", block, flags=re.S | re.I)
        summary_match = re.search(
            r'<div[^>]+class="[^"]*text-\[15px\][^"]*text-surface-500[^"]*"[^>]*>(.*?)</div>',
            block,
            flags=re.S | re.I,
        )
        meta_match = re.search(
            r'<div[^>]+class="[^"]*text-sm[^"]*text-gray-400[^"]*"[^>]*>(.*?)</div>',
            block,
            flags=re.S | re.I,
        )

        title = clean_html_fragment(title_match.group(1), 140) if title_match else ""
        summary = clean_html_fragment(summary_match.group(1), 420) if summary_match else ""
        meta = clean_html_fragment(meta_match.group(1), 100) if meta_match else ""
        if not title:
            label_match = re.search(r'aria-label="阅读文章:\s*([^"]+)"', block, flags=re.S | re.I)
            title = clean_html_fragment(label_match.group(1), 140) if label_match else ""

        published_at, display_date = parse_cn_news_datetime(summary)
        if not published_at:
            published_at, display_date = parse_cn_news_datetime(meta)

        if not title or not item_url.startswith("http"):
            continue
        items.append(
            {
                "title": title,
                "summary": summary,
                "url": item_url,
                "published_at": published_at,
                "date": display_date,
                "source": source.get("name", "AIbase"),
                "source_priority": source.get("priority", 0),
                "official_source": False,
            }
        )
    return items


def parse_source(raw: bytes, source: Dict[str, Any], url: str) -> List[Dict[str, Any]]:
    source_type = source.get("type", "rss")
    if source_type == "aibase_news":
        return parse_aibase_news(raw, source, url)
    if source_type == "sogou_news":
        return parse_sogou_news(raw, source, url)
    if source_type == "so360_news":
        return parse_so360_news(raw, source, url)
    return parse_feed(raw, source)


def in_time_window(item: Dict[str, Any], start: dt.datetime, end: dt.datetime) -> bool:
    parsed = parse_dt(item.get("published_at"))
    if parsed is None:
        return True
    return start <= parsed <= end + dt.timedelta(hours=12)


def fetch_one_source(
    source: Dict[str, Any],
    lookback_days: int,
    start: dt.datetime,
    end: dt.datetime,
    timeout_seconds: int,
) -> Tuple[List[Dict[str, Any]], Optional[str], str]:
    try:
        url = source_url(source, lookback_days)
        raw = fetch_url(url, timeout=timeout_seconds)
        parsed = parse_source(raw, source, url)
        filtered = [item for item in parsed if in_time_window(item, start, end)]
        return filtered, None, f"Fetched {len(filtered):>3} items from {source.get('name')}"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ET.ParseError, ValueError, OSError) as exc:
        error = f"{source.get('name', 'unknown source')}: {exc}"
        return [], error, f"Failed source: {source.get('name')} ({exc})"


def fetch_candidates(settings: Dict[str, Any]) -> FetchResult:
    lookback_days = int(settings.get("lookback_days", 8))
    start, end = week_range(lookback_days)
    all_items: List[Dict[str, Any]] = []
    errors: List[str] = []
    enabled_sources = [source for source in settings.get("sources", []) if source.get("enabled", True)]
    timeout_seconds = int(settings.get("fetch_timeout_seconds", 8))
    max_workers = max(1, int(settings.get("max_workers", 6)))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(fetch_one_source, source, lookback_days, start, end, timeout_seconds)
            for source in enabled_sources
        ]
        for future in concurrent.futures.as_completed(futures):
            items, error, message = future.result()
            print(message)
            all_items.extend(items)
            if error:
                errors.append(error)

    return FetchResult(items=all_items, errors=errors)


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urllib.parse.urlsplit(url.strip())
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if not k.lower().startswith("utm_")]
    clean_query = urllib.parse.urlencode(query)
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), clean_query, "")
    )


def item_key(item: Dict[str, Any]) -> str:
    url = normalize_url(item.get("url", ""))
    if url:
        return "url:" + url
    title = compact_text(item.get("title", "")).lower()
    return "title:" + hashlib.sha1(title.encode("utf-8")).hexdigest()


def event_key(item: Dict[str, Any]) -> str:
    text = haystack(item)
    event_markers = [
        ("ai版支付宝", "alipay_ai_app"),
        ("ai 版支付宝", "alipay_ai_app"),
        ("阿宝", "alipay_ai_app"),
        ("agentar", "ant_agentar"),
        ("ai专属卡", "wechat_ai_payment_card"),
        ("微信支付测试ai支付", "wechat_ai_payment_card"),
        ("微信ai生态", "wechat_ai_ecosystem"),
        ("微信 ai 生态", "wechat_ai_ecosystem"),
        ("开发者接入微信ai", "wechat_ai_ecosystem"),
        ("悟空", "alibaba_wukong_agent"),
        ("meoo cli", "alibaba_meoo_cli"),
        ("秒悟", "alibaba_meoo_cli"),
    ]
    for marker, key in event_markers:
        if marker in text:
            return key
    return item_key(item)


def dedupe(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key = item_key(item)
        if key not in seen:
            seen[key] = item
            continue
        old = seen[key]
        old_score = int(old.get("source_priority", 0)) + int(old.get("official_source", False))
        new_score = int(item.get("source_priority", 0)) + int(item.get("official_source", False))
        if new_score > old_score:
            seen[key] = item
    return list(seen.values())


def haystack(item: Dict[str, Any]) -> str:
    return " ".join(
        compact_text(str(item.get(key, ""))).lower()
        for key in ("title", "summary", "company", "source", "tags")
    )


def hits(text: str, keywords: Iterable[str]) -> List[str]:
    found = []
    for keyword in keywords:
        keyword_lower = keyword.lower()
        if keyword_lower and keyword_lower in text:
            found.append(keyword)
    return found


def title_text(item: Dict[str, Any]) -> str:
    return compact_text(str(item.get("title", ""))).lower()


def is_question_or_analysis(item: Dict[str, Any]) -> bool:
    title = title_text(item)
    weak_markers = [
        "?",
        "？",
        "如何",
        "为什么",
        "背后",
        "解读",
        "观察",
        "评论",
        "盘点",
        "周报",
        "早报",
        "晨报",
        "战略",
        "生态博弈",
        "未来",
        "要来了",
        "不打算",
        "优势和瓶颈",
        "融合的这步",
    ]
    if len(title) <= 8 and not hits(title, ["发布", "上线", "开放", "新增", "推出"]):
        return True
    return any(marker.lower() in title for marker in weak_markers)


def is_roundup(item: Dict[str, Any]) -> bool:
    title = title_text(item)
    return bool(re.search(r"\d+月\d+日.*(新产品讯息|早报|晨报|日报|周报)", title))


def guess_company(item: Dict[str, Any], settings: Dict[str, Any]) -> str:
    if item.get("company"):
        return str(item["company"])
    text = haystack(item)
    for group in ("priority_companies", "known_companies"):
        for company in settings.get(group, []):
            if company.lower() in text:
                return company
    return "相关平台"


def is_model_only(text: str, settings: Dict[str, Any]) -> Tuple[bool, List[str]]:
    model_hits = hits(text, settings.get("model_update_keywords", []))
    if not model_hits:
        return False, []
    product_hits = hits(text, settings.get("product_keywords", []))
    commerce_hits = hits(text, settings.get("ecommerce_keywords", []))
    if product_hits or commerce_hits:
        return False, model_hits
    return True, model_hits


def score_item(item: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    text = haystack(item)
    reasons: List[str] = []
    score = float(item.get("source_priority", 0))

    hard_exclude = hits(text, settings.get("hard_exclude_keywords", []))
    if hard_exclude:
        item["excluded"] = True
        item["exclude_reason"] = "排除词：" + "、".join(hard_exclude[:4])
        item["score"] = -10
        item["score_reasons"] = []
        return item

    if is_roundup(item):
        item["excluded"] = True
        item["exclude_reason"] = "排除聚合/早报标题"
        item["score"] = -8
        item["score_reasons"] = []
        return item

    model_only, model_hits = is_model_only(text, settings)
    if model_only:
        item["excluded"] = True
        item["exclude_reason"] = "疑似纯模型更新：" + "、".join(model_hits[:4])
        item["score"] = -5
        item["score_reasons"] = []
        return item

    priority_company_hits = hits(text, settings.get("priority_companies", []))
    known_company_hits = hits(text, settings.get("known_companies", []))
    ecommerce_hits = hits(text, settings.get("ecommerce_keywords", []))
    product_hits = hits(text, settings.get("product_keywords", []))
    action_hits = hits(text, settings.get("action_keywords", []))

    if priority_company_hits:
        score += 4
        reasons.append("阿里/重点公司：" + "、".join(priority_company_hits[:3]))
    elif known_company_hits:
        score += 2
        reasons.append("知名公司：" + "、".join(known_company_hits[:3]))

    if ecommerce_hits:
        score += 3
        reasons.append("电商/交易相关：" + "、".join(ecommerce_hits[:3]))

    if product_hits:
        score += min(5, 1.4 * len(product_hits))
        reasons.append("产品/功能信号：" + "、".join(product_hits[:4]))

    if action_hits:
        score += min(3, 1.0 * len(action_hits))
        reasons.append("发布动作：" + "、".join(action_hits[:4]))

    if is_question_or_analysis(item):
        score -= 5
        reasons.append("标题像分析/评论，降权")

    if item.get("official_source"):
        score += 1.5
        reasons.append("官方来源")

    if "aibase" in compact_text(item.get("source", "")).lower():
        score += 1
        reasons.append("AIbase 来源")

    if model_hits:
        score -= 1
        reasons.append("含模型词，需人工确认")

    if not product_hits and not action_hits:
        score -= 2
        reasons.append("产品信号偏弱")

    item["excluded"] = False
    item["score"] = round(score, 1)
    item["score_reasons"] = reasons
    item["company_guess"] = guess_company(item, settings)
    return item


def load_json_items(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise ValueError(f"Unsupported candidate file format: {path}")


def load_manual_items(path: Path = INBOX_FILE) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                item = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Bad JSONL at {path}:{line_no}: {exc}") from exc
            item.setdefault("source", "手动补充")
            item.setdefault("source_priority", 4)
            items.append(item)
    return items


def latest_candidate_file() -> Optional[Path]:
    files = sorted(DATA_DIR.glob("candidates-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def first_sentence(text: str, limit: int = 95) -> str:
    text = compact_text(text)
    if not text:
        return ""
    parts = re.split(r"(?<=[。.!?？；;])\s*", text)
    sentence = parts[0] if parts else text
    return compact_text(sentence, limit)


def source_lead(text: str, limit: int = 180) -> str:
    text = compact_text(text)
    if not text:
        return ""
    parts = re.split(r"(?<=[。.!?？；;])\s*", text)
    if len(parts) >= 2 and len(parts[0]) < 55:
        lead = parts[0] + parts[1]
    else:
        lead = parts[0]
    return compact_text(lead, limit)


def clean_title_for_brief(title: str) -> str:
    title = compact_text(title, 120)
    title = re.sub(r"[_-](腾讯新闻|新浪财经|新浪网)$", "", title).strip()
    title = re.sub(r"^【[^】]+】", "", title).strip()
    if "丨" in title:
        prefix, rest = title.split("丨", 1)
        if any(marker in prefix for marker in ("观察", "早报", "晨报", "周报", "资讯")):
            title = rest.strip()
    if ":" in title or "：" in title:
        parts = re.split(r"[:：]", title, maxsplit=1)
        if len(parts) == 2 and any(marker in parts[0] for marker in ("新产品讯息", "早报", "晨报", "周报")):
            title = parts[1].strip()
    return compact_text(title, 70)


def guess_action(text: str) -> str:
    actions = [
        ("正式发布", "发布"),
        ("发布", "发布"),
        ("正式推出", "推出"),
        ("推出", "推出"),
        ("正式上线", "上线"),
        ("上线", "上线"),
        ("开放接入", "开放接入"),
        ("接入", "开放接入"),
        ("开放", "开放"),
        ("新增", "新增"),
        ("升级", "升级"),
        ("内测", "开放内测"),
        ("公测", "开放公测"),
        ("rolls out", "上线"),
        ("launches", "推出"),
        ("unveils", "发布"),
    ]
    lower = text.lower()
    for marker, action in actions:
        if marker.lower() in lower:
            return action
    return "报道"


def make_brief(item: Dict[str, Any], settings: Dict[str, Any]) -> str:
    if item.get("draft"):
        return compact_text(str(item["draft"]))

    item_date = compact_text(str(item.get("date", ""))) or date_cn(item.get("published_at"))
    company = item.get("company_guess") or guess_company(item, settings)
    title = clean_title_for_brief(item.get("title", ""))
    summary = source_lead(item.get("summary", ""), 180)
    action = guess_action(title)
    if action == "报道":
        action = guess_action(summary)

    if summary and summary != title:
        return f"{item_date}，{company}{action}“{title}”。{summary}"
    if action == "报道":
        return f"{item_date}，{company}相关动态：“{title}”。"
    return f"{item_date}，{company}{action}“{title}”。"


def item_category(item: Dict[str, Any], settings: Dict[str, Any]) -> str:
    text = haystack(item)
    if hits(text, settings.get("priority_companies", [])) or hits(text, settings.get("ecommerce_keywords", [])):
        return "阿里 / 电商重点"

    domestic_markers = [
        "微信",
        "腾讯",
        "京东",
        "拼多多",
        "美团",
        "小红书",
        "快手",
        "字节",
        "抖音",
        "火山引擎",
        "飞书",
        "百度",
        "华为",
        "小米",
        "蚂蚁",
    ]
    if hits(text, domestic_markers):
        return "国内大厂"
    return "海外大厂 / 知名产品"


def markdown_link(title: str, url: str) -> str:
    title = title.replace("[", "【").replace("]", "】")
    if not url:
        return title
    return f"[{title}]({url})"


def is_strong_match(item: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    text = haystack(item)
    score = float(item.get("score", 0))
    has_priority = bool(hits(text, settings.get("priority_companies", [])))
    has_commerce = bool(hits(text, settings.get("ecommerce_keywords", [])))
    has_known = bool(hits(text, settings.get("known_companies", [])))
    has_product = bool(hits(text, settings.get("product_keywords", [])))
    has_action = bool(hits(text, settings.get("action_keywords", [])))
    reliable_source = item.get("official_source") or "aibase" in compact_text(item.get("source", "")).lower()
    return (
        score >= float(settings.get("min_score", 6)) + 6
        and has_product
        and has_action
        and (has_priority or has_commerce or (has_known and reliable_source))
        and not is_question_or_analysis(item)
    )


def split_featured_backup(items: List[Dict[str, Any]], settings: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    featured: List[Dict[str, Any]] = []
    backup: List[Dict[str, Any]] = []
    for item in items:
        if is_strong_match(item, settings):
            featured.append(item)
        else:
            backup.append(item)
    return featured, backup


def append_markdown_items(
    lines: List[str],
    items: List[Dict[str, Any]],
    settings: Dict[str, Any],
    start_index: int = 1,
) -> int:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item_category(item, settings), []).append(item)

    index = start_index
    for category in ("阿里 / 电商重点", "国内大厂", "海外大厂 / 知名产品"):
        category_items = grouped.get(category, [])
        if not category_items:
            continue
        lines.append(f"### {category}")
        lines.append("")
        for item in category_items:
            brief = make_brief(item, settings)
            source_title = compact_text(item.get("title", "来源"), 80)
            source_url_value = compact_text(item.get("url", ""))
            reasons = "；".join(item.get("score_reasons", []))
            lines.append(f"{index}. [ ] {brief}")
            lines.append(f"   来源：{markdown_link(source_title, source_url_value)}")
            lines.append(f"   评分：{item.get('score')}；理由：{reasons or '手动候选'}")
            lines.append("")
            index += 1
    return index


def render_draft(items: List[Dict[str, Any]], excluded: List[Dict[str, Any]], settings: Dict[str, Any]) -> str:
    lookback_days = int(settings.get("lookback_days", 8))
    start, end = week_range(lookback_days)
    min_score = float(settings.get("min_score", 6))

    lines: List[str] = []
    lines.append(f"# 本周 AI 产品/功能动态草稿（{week_key()}）")
    lines.append("")
    lines.append(f"生成时间：{now_cn().strftime('%Y-%m-%d %H:%M')}  ")
    lines.append(f"覆盖范围：{start.strftime('%Y-%m-%d')} 至 {end.strftime('%Y-%m-%d')}  ")
    lines.append(f"筛选阈值：{min_score:g} 分")
    lines.append("")
    featured, backup = split_featured_backup(items, settings)
    lines.append("## 更符合要求（请人工核验）")
    lines.append("")

    if not featured:
        lines.append("> 暂无达到阈值的候选。可以先运行 `python3 weekly_ai_news.py add` 手动补充重要链接，再重新生成草稿。")
    for index, item in enumerate(featured, start=1):
        lines.append(f"{index}. {make_brief(item, settings)}")

    lines.append("")
    lines.append("## 备选线索（优先级较低）")
    lines.append("")
    if not backup:
        lines.append("- 无")
    for index, item in enumerate(backup, start=1):
        lines.append(f"{index}. {make_brief(item, settings)}")

    lines.append("")
    lines.append("## 更符合要求（带来源和评分）")
    lines.append("")
    append_markdown_items(lines, featured, settings)

    lines.append("")
    lines.append("## 备选线索（带来源和评分）")
    lines.append("")
    if backup:
        append_markdown_items(lines, backup, settings)
    else:
        lines.append("- 无")

    lines.append("## 候选池")
    lines.append("")
    for item in items:
        lines.append(
            f"- {item.get('score')} 分｜{compact_text(item.get('source', ''))}｜"
            f"{markdown_link(compact_text(item.get('title', ''), 90), compact_text(item.get('url', '')))}"
        )

    lines.append("")
    lines.append("## 自动排除项")
    lines.append("")
    if not excluded:
        lines.append("- 无")
    else:
        for item in excluded[:40]:
            lines.append(
                f"- {compact_text(item.get('exclude_reason', '排除'), 60)}｜"
                f"{markdown_link(compact_text(item.get('title', ''), 90), compact_text(item.get('url', '')))}"
            )

    lines.append("")
    lines.append("## 人工改写提示")
    lines.append("")
    lines.append("需要更像正式周报时，把“精选短讯”复制到大模型里，并使用 " + str(PROMPT_FILE) + " 的提示词。")
    lines.append("")
    return "\n".join(lines)


def escape_html(value: Any) -> str:
    return html.escape(compact_text(str(value)), quote=True)


def range_label(start: dt.datetime, end: dt.datetime) -> str:
    if start.year == end.year:
        return f"{start.month}.{start.day}-{end.month}.{end.day}"
    return f"{start.year}.{start.month}.{start.day}-{end.year}.{end.month}.{end.day}"


def display_range(start: dt.datetime, end: dt.datetime) -> str:
    if start.year == end.year:
        return f"{start.month}月{start.day}日 - {end.month}月{end.day}日"
    return f"{start.year}年{start.month}月{start.day}日 - {end.year}年{end.month}月{end.day}日"


def site_css() -> str:
    return """
:root {
  color-scheme: light;
  --bg: #f6f7f9;
  --surface: #ffffff;
  --ink: #1b1f24;
  --muted: #657282;
  --line: #dfe4ea;
  --accent: #1f6feb;
  --accent-soft: #e8f1ff;
  --focus: #0f766e;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.65;
}

a {
  color: inherit;
}

.shell {
  width: min(1040px, calc(100% - 32px));
  margin: 0 auto;
}

.topbar {
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}

.topbar .shell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 64px;
}

.brand {
  font-size: 20px;
  font-weight: 700;
  text-decoration: none;
}

.meta {
  color: var(--muted);
  font-size: 14px;
}

main {
  padding: 28px 0 48px;
}

.page-head {
  display: grid;
  gap: 6px;
  margin-bottom: 22px;
}

h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.25;
  letter-spacing: 0;
}

h2 {
  margin: 28px 0 12px;
  font-size: 18px;
  letter-spacing: 0;
}

.week-list {
  display: grid;
  gap: 12px;
}

.week-link,
.news-item {
  display: block;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px;
  text-decoration: none;
}

.week-link:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.week-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  font-weight: 700;
  font-size: 18px;
}

.summary-line {
  color: var(--muted);
  margin-top: 6px;
  font-size: 14px;
}

.news-list {
  display: grid;
  gap: 12px;
}

.news-item p {
  margin: 0;
}

.brief {
  font-size: 16px;
}

.source {
  margin-top: 10px;
  color: var(--muted);
  font-size: 14px;
}

.source a {
  color: var(--accent);
  text-decoration: none;
}

.source a:hover {
  text-decoration: underline;
}

.score {
  margin-top: 6px;
  color: var(--muted);
  font-size: 13px;
}

.back {
  color: var(--accent);
  text-decoration: none;
  font-size: 14px;
}

.empty {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  color: var(--muted);
}

@media (max-width: 640px) {
  .topbar .shell,
  .week-title {
    align-items: flex-start;
    flex-direction: column;
  }

  h1 {
    font-size: 24px;
  }
}
""".strip()


def read_site_entries() -> List[Dict[str, Any]]:
    if not SITE_INDEX_FILE.exists():
        return []
    with SITE_INDEX_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def write_site_entries(entries: List[Dict[str, Any]]) -> None:
    with SITE_INDEX_FILE.open("w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def render_site_index(entries: List[Dict[str, Any]]) -> str:
    cards: List[str] = []
    for entry in entries:
        title = escape_html(entry.get("label", entry.get("week", "")))
        href = escape_html(entry.get("href", ""))
        full_range = escape_html(entry.get("display_range", ""))
        count = int(entry.get("item_count", 0))
        updated = escape_html(entry.get("updated_at", ""))
        cards.append(
            f"""
      <a class="week-link" href="{href}">
        <div class="week-title">
          <span>{title}</span>
          <span class="meta">{count} 条</span>
        </div>
        <div class="summary-line">{full_range} · 更新于 {updated}</div>
      </a>""".rstrip()
        )

    content = "\n".join(cards) if cards else '<div class="empty">还没有生成周报。运行 python3 -B weekly_ai_news.py run 后会出现在这里。</div>'
    generated = escape_html(now_cn().strftime("%Y-%m-%d %H:%M"))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI 新闻资讯周报</title>
  <link rel="stylesheet" href="assets/site.css">
</head>
<body>
  <header class="topbar">
    <div class="shell">
      <a class="brand" href="index.html">AI 新闻资讯周报</a>
      <div class="meta">每周四更新</div>
    </div>
  </header>
  <main class="shell">
    <section class="page-head">
      <h1>按周查看相关新闻</h1>
      <div class="meta">点击日期区间进入当周内容。最后生成：{generated}</div>
    </section>
    <section class="week-list">
{content}
    </section>
  </main>
</body>
</html>
"""


def render_site_week(
    items: List[Dict[str, Any]],
    excluded: List[Dict[str, Any]],
    settings: Dict[str, Any],
    start: dt.datetime,
    end: dt.datetime,
) -> str:
    def render_group(title: str, group_items: List[Dict[str, Any]]) -> str:
        if not group_items:
            return f"""
      <section>
        <h2>{escape_html(title)}</h2>
        <div class="empty">无</div>
      </section>""".rstrip()
        rows: List[str] = []
        for item in group_items:
            brief = escape_html(make_brief(item, settings))
            source_title = escape_html(item.get("title", "来源"))
            source_url = escape_html(item.get("url", ""))
            reasons = escape_html("；".join(item.get("score_reasons", [])))
            score = escape_html(item.get("score", ""))
            source_link = (
                f'<a href="{source_url}" target="_blank" rel="noopener">{source_title}</a>'
                if source_url
                else source_title
            )
            rows.append(
                f"""
        <article class="news-item">
          <p class="brief">{brief}</p>
          <p class="source">来源：{source_link}</p>
          <p class="score">评分：{score} · {reasons}</p>
        </article>""".rstrip()
            )
        return f"""
      <section>
        <h2>{escape_html(title)}</h2>
        <div class="news-list">
{chr(10).join(rows)}
        </div>
      </section>""".rstrip()

    featured, backup = split_featured_backup(items, settings)
    sections = [
        render_group("更符合要求", featured),
        render_group("备选线索", backup),
    ]

    label = escape_html(range_label(start, end))
    full_range = escape_html(display_range(start, end))
    generated = escape_html(now_cn().strftime("%Y-%m-%d %H:%M"))
    excluded_count = len(excluded)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{label} AI 新闻资讯</title>
  <link rel="stylesheet" href="../assets/site.css">
</head>
<body>
  <header class="topbar">
    <div class="shell">
      <a class="brand" href="../index.html">AI 新闻资讯周报</a>
      <a class="back" href="../index.html">返回周列表</a>
    </div>
  </header>
  <main class="shell">
    <section class="page-head">
      <h1>{label}</h1>
      <div class="meta">{full_range} · 精选 {len(items)} 条 · 自动排除 {excluded_count} 条 · 更新于 {generated}</div>
    </section>
{chr(10).join(sections)}
  </main>
</body>
</html>
"""


def rebuild_site(items: List[Dict[str, Any]], excluded: List[Dict[str, Any]], settings: Dict[str, Any]) -> Path:
    SITE_WEEKS_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "assets").mkdir(parents=True, exist_ok=True)

    lookback_days = int(settings.get("lookback_days", 8))
    start, end = week_range(lookback_days)
    key = week_key()
    page_name = f"{key}.html"
    page_path = SITE_WEEKS_DIR / page_name
    page_path.write_text(render_site_week(items, excluded, settings, start, end), encoding="utf-8")
    (SITE_DIR / "assets" / "site.css").write_text(site_css() + "\n", encoding="utf-8")

    entries = [entry for entry in read_site_entries() if entry.get("week") != key]
    entries.append(
        {
            "week": key,
            "label": range_label(start, end),
            "display_range": display_range(start, end),
            "href": f"weeks/{page_name}",
            "item_count": len(items),
            "range_start": start.isoformat(),
            "range_end": end.isoformat(),
            "updated_at": now_cn().strftime("%Y-%m-%d %H:%M"),
        }
    )
    entries.sort(key=lambda entry: entry.get("range_end", ""), reverse=True)
    write_site_entries(entries)
    (SITE_DIR / "index.html").write_text(render_site_index(entries), encoding="utf-8")
    return SITE_DIR / "index.html"


def command_fetch(args: argparse.Namespace) -> int:
    ensure_dirs()
    settings = load_settings()
    if args.days is not None:
        settings["lookback_days"] = args.days
    result = fetch_candidates(settings)
    output = DATA_DIR / f"candidates-{week_key()}.json"
    payload = {
        "generated_at": now_cn().isoformat(),
        "items": result.items,
        "errors": result.errors,
    }
    with output.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(result.items)} raw candidates to {output}")
    if result.errors:
        print("Some sources failed:")
        for error in result.errors:
            print(" - " + error)
    return 0


def command_draft(args: argparse.Namespace) -> int:
    ensure_dirs()
    settings = load_settings()
    if args.days is not None:
        settings["lookback_days"] = args.days
    if args.min_score is not None:
        settings["min_score"] = args.min_score

    input_path = getattr(args, "input", None)
    candidate_file = Path(input_path).resolve() if input_path else latest_candidate_file()
    fetched_items = load_json_items(candidate_file) if candidate_file else []
    manual_items = load_manual_items()
    merged = dedupe([*manual_items, *fetched_items])
    scored = [score_item(item, settings) for item in merged]

    min_score = float(settings.get("min_score", 6))
    selected = [item for item in scored if not item.get("excluded") and float(item.get("score", 0)) >= min_score]
    selected.sort(key=lambda item: (float(item.get("score", 0)), item.get("published_at", "")), reverse=True)

    unique_selected: List[Dict[str, Any]] = []
    seen_events: set[str] = set()
    for item in selected:
        key = event_key(item)
        if key in seen_events:
            continue
        seen_events.add(key)
        unique_selected.append(item)
        if len(unique_selected) >= int(settings.get("max_items", 8)):
            break
    selected = unique_selected
    excluded = [item for item in scored if item.get("excluded")]

    output = OUTPUT_DIR / f"{week_key()}-ai-news-draft.md"
    output.write_text(render_draft(selected, excluded, settings), encoding="utf-8")
    site_index = rebuild_site(selected, excluded, settings)
    print(f"Selected {len(selected)} items from {len(merged)} candidates")
    print(f"Draft saved to {output}")
    print(f"Site updated at {site_index}")
    return 0


def command_run(args: argparse.Namespace) -> int:
    fetch_code = command_fetch(args)
    if fetch_code != 0:
        return fetch_code
    return command_draft(args)


def prompt_value(label: str, current: Optional[str] = None) -> str:
    suffix = f" [{current}]" if current else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or current or ""


def command_add(args: argparse.Namespace) -> int:
    ensure_dirs()
    item = {
        "date": args.date or "",
        "company": args.company or "",
        "title": args.title or "",
        "url": args.url or "",
        "summary": args.summary or "",
        "draft": args.draft or "",
        "source": "手动补充",
        "source_priority": 4,
    }

    if not any(item[key] for key in ("title", "url", "summary", "draft")):
        print("Enter a manual news candidate. Leave fields blank if unknown.")
        item["date"] = prompt_value("日期，例如 6月11日", item["date"])
        item["company"] = prompt_value("公司/平台", item["company"])
        item["title"] = prompt_value("标题", item["title"])
        item["url"] = prompt_value("链接", item["url"])
        item["summary"] = prompt_value("摘要", item["summary"])
        item["draft"] = prompt_value("已改好的短讯（可空）", item["draft"])

    if not any(item[key] for key in ("title", "url", "summary", "draft")):
        print("Nothing added.")
        return 1

    with INBOX_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Added manual item to {INBOX_FILE}")
    return 0


def command_sources(_: argparse.Namespace) -> int:
    settings = load_settings()
    for source in settings.get("sources", []):
        status = "on " if source.get("enabled", True) else "off"
        print(f"{status} {source.get('name')} ({source.get('type', 'rss')})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a semi-automatic weekly AI product/function news brief.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Common usage:
              python3 weekly_ai_news.py run
              python3 weekly_ai_news.py add --date 6月11日 --company 阿里云 --title "..." --url "..."
              python3 weekly_ai_news.py draft --min-score 5
            """
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch candidate news from configured sources.")
    fetch_parser.add_argument("--days", type=int, help="Lookback days. Default comes from config/settings.json.")
    fetch_parser.set_defaults(func=command_fetch)

    draft_parser = subparsers.add_parser("draft", help="Score candidates and write a Markdown draft.")
    draft_parser.add_argument("--input", help="Candidate JSON file. Defaults to the latest data/candidates-*.json.")
    draft_parser.add_argument("--days", type=int, help="Lookback days. Default comes from config/settings.json.")
    draft_parser.add_argument("--min-score", type=float, help="Override minimum score.")
    draft_parser.set_defaults(func=command_draft)

    run_parser = subparsers.add_parser("run", help="Fetch candidates, then write the weekly draft.")
    run_parser.add_argument("--days", type=int, help="Lookback days. Default comes from config/settings.json.")
    run_parser.add_argument("--min-score", type=float, help="Override minimum score.")
    run_parser.set_defaults(func=command_run)

    add_parser = subparsers.add_parser("add", help="Append one manual candidate to inbox/manual_items.jsonl.")
    add_parser.add_argument("--date", help="Chinese date, for example 6月11日.")
    add_parser.add_argument("--company", help="Company/platform name.")
    add_parser.add_argument("--title", help="News title.")
    add_parser.add_argument("--url", help="Source URL.")
    add_parser.add_argument("--summary", help="Short source summary.")
    add_parser.add_argument("--draft", help="Already polished final brief.")
    add_parser.set_defaults(func=command_add)

    sources_parser = subparsers.add_parser("sources", help="List configured sources.")
    sources_parser.set_defaults(func=command_sources)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
