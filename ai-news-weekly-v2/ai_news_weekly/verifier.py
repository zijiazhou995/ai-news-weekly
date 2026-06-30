from typing import List

from .models import EditedArticle, VerifiedArticle
from .utils import in_date_range


def verify_article(edited: EditedArticle, start_date, end_date) -> VerifiedArticle:
    article = edited.article
    reasons: List[str] = []

    if edited.category not in {"preferred", "lead", "needs_review", "excluded"}:
        reasons.append("分类值非法")
    if edited.category == "excluded":
        reasons.append("编辑阶段已排除")
    if not article.url.startswith("https://www.aibase.com/zh/news/"):
        reasons.append("详情页 URL 不是 AIbase 中文新闻详情页")
    if article.source_id and not article.url.rstrip("/").endswith(article.source_id):
        reasons.append("详情页 URL 与 source_id 不一致")
    if not in_date_range(article.date, start_date, end_date):
        reasons.append("日期不在本周窗口内")
    if not article.title or len(article.title) < 6:
        reasons.append("标题为空或过短")
    if not (article.lead or article.description or article.first_paragraph):
        reasons.append("未提取到导语或正文首段")
    if not edited.summary.startswith(article.date):
        reasons.append("摘要未按日期开头")
    passed = not reasons
    return VerifiedArticle(edited=edited, passed=passed, verifier_reasons=reasons)
