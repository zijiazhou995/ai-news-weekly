import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from .models import Article, EditedArticle
from .rules import classify_by_rules, reason_from_hits


SYSTEM_PROMPT = """你是 AI 资讯周报编辑。请严格按用户筛选标准判断新闻。
只返回 JSON：category 为 preferred、lead、needs_review、excluded 之一；
summary 尽量贴近原新闻导语或正文首段，必须以日期开头；
ai_summary 需要更凝练地概括资讯内容，风格要接近示例中的周报口吻；
lead_excerpt 需要更接近原文导语/首段，不要过度改写；
reason 用一句中文说明纳入或排除理由；
priority_score 为 0-100 整数。
不要纳入融资、人事、财报、评论、分析、盘点、行业观察、教程、案例文章、旧闻、纯模型更新。"""


def edit_article(article: Article, mode: str = "auto") -> EditedArticle:
    samples = load_summary_samples(Path(__file__).resolve().parents[1] / "config" / "summaries.json")
    category, score, hits, rejects = classify_by_rules(article)
    summary = build_summary(article)
    ai_summary = summary
    lead_excerpt = build_lead_excerpt(article)
    reason = reason_from_hits(category, hits, rejects)
    decision_source = "rules"

    if mode in {"auto", "ai"} and os.environ.get("OPENAI_API_KEY"):
        try:
            ai_decision = call_openai_compatible_editor(article, category, score, hits, rejects, samples)
            category = ai_decision.get("category", category)
            summary = ai_decision.get("summary", summary) or summary
            ai_summary = ai_decision.get("ai_summary", ai_summary) or ai_summary
            lead_excerpt = ai_decision.get("lead_excerpt", lead_excerpt) or lead_excerpt
            reason = ai_decision.get("reason", reason) or reason
            score = int(ai_decision.get("priority_score", score))
            decision_source = "ai"
        except Exception as exc:
            if mode == "ai":
                raise
            reason = f"{reason}；AI 编辑不可用，已使用规则判断（{exc}）"

    return EditedArticle(
        article=article,
        category=category,
        summary=summary,
        ai_summary=ai_summary,
        lead_excerpt=lead_excerpt,
        reason=reason,
        priority_score=score,
        decision_source=decision_source,
        rule_hits=hits,
        reject_reasons=rejects,
    )


def build_summary(article: Article) -> str:
    basis = article.lead or article.description or article.first_paragraph
    basis = basis.strip()
    if len(basis) > 180:
        basis = basis[:177].rstrip() + "..."
    if basis.startswith(article.date):
        return basis
    return f"{article.date}，{basis}"


def build_lead_excerpt(article: Article) -> str:
    basis = article.lead or article.description or article.first_paragraph
    basis = basis.strip()
    if len(basis) > 120:
        basis = basis[:117].rstrip() + "..."
    return basis


def call_openai_compatible_editor(
    article: Article,
    rule_category: str,
    rule_score: int,
    rule_hits: List[str],
    rule_rejects: List[str],
    samples: List[Dict[str, str]],
) -> Dict[str, Any]:
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    payload = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "article": article.to_dict(),
                        "rule_category": rule_category,
                        "rule_score": rule_score,
                        "rule_hits": rule_hits,
                        "rule_rejects": rule_rejects,
                        "style_samples": samples,
                        "task": "请输出 ai_summary 和 lead_excerpt；lead_excerpt 需尽量贴近原文线索，ai_summary 需更凝练概括新闻内容，均保持事实准确。",
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        data = json.loads(response.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    return json.loads(content)


def load_summary_samples(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            cleaned = []
            for item in data:
                if isinstance(item, dict):
                    cleaned.append(
                        {
                            "title": str(item.get("title", "")),
                            "source_text": str(item.get("source_text", "")),
                            "summary": str(item.get("summary", "")),
                        }
                    )
            return cleaned[:20]
    except json.JSONDecodeError:
        pass
    return []
