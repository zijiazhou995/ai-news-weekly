import argparse
import datetime as dt
from pathlib import Path
from typing import Any, Dict, List

from .crawler import crawl_detail_pages
from .editor import edit_article
from .extractor import extract_from_crawl_index
from .models import EditedArticle, VerifiedArticle, WeekOutput
from .site import generate_site
from .utils import default_week, read_json, week_id, week_label, write_json
from .verifier import verify_article


def run_pipeline(args: argparse.Namespace) -> Dict[str, Any]:
    root = Path(args.root).resolve()
    config = read_json(root / "config" / "settings.json")

    today = (
        dt.datetime.strptime(args.today, "%Y-%m-%d").date()
        if args.today
        else dt.date.today()
    )
    start, end = default_week(today)
    if args.start:
        start = dt.datetime.strptime(args.start, "%Y-%m-%d").date()
    if args.end:
        end = dt.datetime.strptime(args.end, "%Y-%m-%d").date()

    raw_dir = root / "data" / "raw" / week_id(start, end)
    index = crawl_detail_pages(
        max_items=args.max_items or config["crawler"]["max_items"],
        raw_dir=raw_dir,
        extra_urls=args.url,
    )
    articles = extract_from_crawl_index(index)
    articles = [a for a in articles if start <= dt.date.fromisoformat(a.date) <= end]

    edited: List[EditedArticle] = [
        edit_article(article, mode=args.editor) for article in articles
    ]
    verified: List[VerifiedArticle] = [
        verify_article(item, start, end) for item in edited
    ]

    preferred = select_items(verified, "preferred", config["output"]["preferred_max"])
    leads = select_items(verified, "lead", config["output"]["leads_max"])

    used_ids = {
        item.edited.article.source_id for item in preferred + leads if item.passed
    }
    needs_review = [
        flatten_verified(item)
        for item in verified
        if item.edited.article.source_id not in used_ids
        and item.edited.category != "excluded"
        and (item.edited.category == "needs_review" or not item.passed)
    ]
    excluded = [
        flatten_verified(item)
        for item in verified
        if item.edited.article.source_id not in used_ids
        and item.edited.category == "excluded"
    ]

    output = WeekOutput(
        week_id=week_id(start, end),
        label=week_label(start, end),
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        generated_at=dt.datetime.now().replace(microsecond=0).isoformat(),
        source="AIbase",
        preferred=[flatten_verified(item) for item in preferred],
        leads=[flatten_verified(item) for item in leads],
        needs_review=needs_review,
        excluded=excluded,
        raw_count=len(index),
        notes=build_notes(preferred, leads, config),
        config=config,
    ).to_dict()

    week_path = root / "data" / "weeks" / f"{output['week_id']}.json"
    write_json(week_path, output)
    generate_site(root / "site", output, root / "data" / "site_weeks.json")
    return output


def select_items(
    verified: List[VerifiedArticle],
    category: str,
    limit: int,
) -> List[VerifiedArticle]:
    items = [item for item in verified if item.passed and item.edited.category == category]
    items.sort(
        key=lambda item: (
            item.edited.article.date,
            item.edited.priority_score,
            int(item.edited.article.source_id or 0),
        ),
        reverse=True,
    )
    return items[:limit]


def flatten_verified(item: VerifiedArticle) -> Dict[str, Any]:
    edited = item.edited
    return {
        "article": edited.article.to_dict(),
        "category": edited.category,
        "summary": edited.summary,
        "reason": edited.reason,
        "priority_score": edited.priority_score,
        "decision_source": edited.decision_source,
        "rule_hits": edited.rule_hits,
        "reject_reasons": edited.reject_reasons,
        "passed_verification": item.passed,
        "verifier_reasons": item.verifier_reasons,
    }


def build_notes(preferred: List[VerifiedArticle], leads: List[VerifiedArticle], config) -> List[str]:
    notes: List[str] = []
    if len(preferred) < config["output"]["preferred_min"]:
        notes.append("更符合要求数量不足，建议补充更多 AIbase 详情页 URL 或扩大抓取窗口。")
    if len(leads) < config["output"]["leads_min"]:
        notes.append("备选线索数量不足，建议补充更多 AIbase 详情页 URL 或扩大抓取窗口。")
    return notes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate AIbase-first weekly AI news site.")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--today", help="Override today's date, YYYY-MM-DD")
    parser.add_argument("--start", help="Week start date, YYYY-MM-DD")
    parser.add_argument("--end", help="Week end date, YYYY-MM-DD")
    parser.add_argument("--max-items", type=int, help="Max AIbase homepage items to crawl")
    parser.add_argument(
        "--editor",
        choices=["auto", "rules", "ai"],
        default="auto",
        help="auto uses AI when OPENAI_API_KEY is present, otherwise rules",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Extra AIbase detail URL to include. Can be used multiple times.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    output = run_pipeline(parser.parse_args())
    print(
        f"Generated {output['label']}: "
        f"{len(output['preferred'])} preferred, {len(output['leads'])} leads."
    )
    if output["notes"]:
        print("Notes:")
        for note in output["notes"]:
            print(f"- {note}")


if __name__ == "__main__":
    main()
