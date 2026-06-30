from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Article:
    source: str
    source_id: str
    url: str
    title: str
    date: str
    lead: str = ""
    first_paragraph: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EditedArticle:
    article: Article
    category: str
    summary: str
    reason: str
    priority_score: int
    decision_source: str
    ai_summary: str = ""
    lead_excerpt: str = ""
    rule_hits: List[str] = field(default_factory=list)
    reject_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["article"] = self.article.to_dict()
        return data


@dataclass
class VerifiedArticle:
    edited: EditedArticle
    passed: bool
    verifier_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["edited"] = self.edited.to_dict()
        return data


@dataclass
class WeekOutput:
    week_id: str
    label: str
    start_date: str
    end_date: str
    generated_at: str
    source: str
    preferred: List[Dict[str, Any]]
    leads: List[Dict[str, Any]]
    needs_review: List[Dict[str, Any]]
    excluded: List[Dict[str, Any]]
    raw_count: int
    notes: List[str] = field(default_factory=list)
    config: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
