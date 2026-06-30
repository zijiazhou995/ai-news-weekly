import datetime as dt
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
)


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch_text(url: str, timeout: int = 25, retries: int = 2, pause: float = 0.8) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, "replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"Fetch failed for {url}: {last_error}")


def absolute_aibase_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        if value.startswith("/zh/news/"):
            return "https://www.aibase.com" + value
        if value.startswith("/news/"):
            return "https://www.aibase.com/zh" + value
        return urllib.parse.urljoin("https://www.aibase.com", value)
    if value.startswith("www."):
        return "https://" + value
    return value


def normalize_space(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class ParagraphHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_block = False
        self.current: List[str] = []
        self.paragraphs: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() in {"p", "h1", "h2", "h3"}:
            self.flush()
            self.in_block = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "h1", "h2", "h3"}:
            self.flush()
            self.in_block = False

    def handle_data(self, data: str) -> None:
        if self.in_block:
            self.current.append(data)

    def flush(self) -> None:
        text = normalize_space("".join(self.current))
        self.current = []
        if text:
            self.paragraphs.append(text)


def html_to_paragraphs(fragment: str) -> List[str]:
    parser = ParagraphHTMLParser()
    parser.feed(html.unescape(fragment or ""))
    parser.flush()
    return [p for p in parser.paragraphs if len(p) >= 8]


def strip_tags(fragment: str) -> str:
    return normalize_space(re.sub(r"<[^>]+>", " ", html.unescape(fragment or "")))


def extract_meta(html_text: str, name: str) -> str:
    escaped = re.escape(name)
    patterns = [
        rf'<meta\s+name="{escaped}"\s+content="([^"]*)"',
        rf'<meta\s+property="{escaped}"\s+content="([^"]*)"',
        rf'<meta\s+content="([^"]*)"\s+name="{escaped}"',
        rf'<meta\s+content="([^"]*)"\s+property="{escaped}"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, re.I)
        if match:
            return normalize_space(match.group(1))
    return ""


def parse_date(value: str) -> Optional[dt.date]:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value[: len(fmt)], fmt).date()
        except ValueError:
            pass
    match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", value)
    if match:
        y, m, d = map(int, match.groups())
        return dt.date(y, m, d)
    return None


def default_week(today: Optional[dt.date] = None) -> Tuple[dt.date, dt.date]:
    end = today or dt.date.today()
    return end - dt.timedelta(days=6), end


def week_id(start: dt.date, end: dt.date) -> str:
    return f"{start.isoformat()}_{end.isoformat()}"


def week_label(start: dt.date, end: dt.date) -> str:
    return f"{start.month}.{start.day}-{end.month}.{end.day}"


def in_date_range(value: str, start: dt.date, end: dt.date) -> bool:
    parsed = parse_date(value)
    return bool(parsed and start <= parsed <= end)


def unique_preserve_order(values: Iterable[str]) -> List[str]:
    seen = set()
    output = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output
