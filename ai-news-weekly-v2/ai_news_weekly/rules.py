from typing import Dict, List, Tuple

from .models import Article


AI_TERMS = ["AI", "人工智能", "大模型", "智能体", "Agent", "AIGC", "生成式"]

PRIMARY_ALI = [
    "阿里",
    "阿里云",
    "支付宝",
    "淘宝",
    "天猫",
    "1688",
    "钉钉",
    "夸克",
    "通义",
    "蚂蚁",
    "高德",
    "菜鸟",
    "闲鱼",
    "饿了么",
    "OceanBase",
]

COMMERCE_TERMS = [
    "电商",
    "交易",
    "支付",
    "商家",
    "导购",
    "客服",
    "营销",
    "投放",
    "订单",
    "收款",
    "广告",
    "零售",
    "店铺",
]

DOMESTIC_MAJORS = [
    "腾讯",
    "微信",
    "京东",
    "字节",
    "豆包",
    "百度",
    "小米",
    "华为",
    "快手",
    "小红书",
    "美团",
    "B站",
    "哔哩哔哩",
]

OVERSEAS_MAJORS = [
    "Google",
    "谷歌",
    "Microsoft",
    "微软",
    "Amazon",
    "亚马逊",
    "OpenAI",
    "Anthropic",
    "Adobe",
    "Notion",
    "Meta",
    "Apple",
    "苹果",
]

PRODUCT_ACTION_TERMS = [
    "发布",
    "推出",
    "上线",
    "开放",
    "接入",
    "升级",
    "新增",
    "内测",
    "公测",
    "上线",
    "入口",
    "工具",
    "平台",
    "协议",
    "功能",
    "版本",
    "智能体",
    "助手",
    "Agent",
    "App",
    "API",
]

EXCLUDE_TERMS = [
    "融资",
    "人事",
    "任命",
    "离职",
    "跳槽",
    "聘请",
    "加盟",
    "财报",
    "股价",
    "评论",
    "盘点",
    "深度分析",
    "行业分析",
    "观察",
    "教程",
    "案例",
    "榜单",
    "报告",
    "调查显示",
    "传记片",
    "电影",
    "论文",
]

PURE_MODEL_TERMS = [
    "模型发布",
    "新模型",
    "开源模型",
    "大模型",
    "Grok",
    "Claude",
    "参数",
    "基准测试",
    "推理模型",
]


def classify_by_rules(article: Article) -> Tuple[str, int, List[str], List[str]]:
    text = " ".join(
        [
            article.title,
            article.description,
            article.lead,
            article.first_paragraph,
            " ".join(article.tags),
        ]
    )
    hits: List[str] = []
    rejects: List[str] = []

    if not any(term.lower() in text.lower() for term in AI_TERMS):
        rejects.append("未明确与 AI 相关")
    title_type_text = " ".join([article.title, " ".join(article.tags)])
    if any(term in title_type_text for term in EXCLUDE_TERMS):
        rejects.append("命中排除类型：融资/人事/财报/评论/盘点/教程/案例等")
    title_text = article.title
    has_model_terms = any(term in text for term in PURE_MODEL_TERMS)
    has_product_surface = any(
        term in text
        for term in ["工具", "平台", "入口", "应用", "App", "API", "数据库", "搜索", "助手", "智能体", "功能"]
    )
    title_has_product_surface = any(
        term in title_text
        for term in ["工具", "平台", "入口", "应用", "App", "API", "数据库", "搜索", "助手", "智能体", "功能"]
    )
    if has_model_terms and (not has_product_surface or not title_has_product_surface):
        rejects.append("疑似纯模型更新")
    if not any(term in text for term in PRODUCT_ACTION_TERMS):
        rejects.append("未识别到新产品/新功能/新工具/新入口/升级等动作")

    score = 0
    if any(term in text for term in PRIMARY_ALI):
        score += 60
        hits.append("阿里及相关主体")
    if any(term in text for term in COMMERCE_TERMS):
        score += 25
        hits.append("电商/交易/支付/商家工具相关")
    if any(term in text for term in DOMESTIC_MAJORS):
        score += 35
        hits.append("国内大厂相关")
    if any(term in text for term in OVERSEAS_MAJORS):
        score += 15
        hits.append("海外大厂或知名 AI 产品")
    if any(term in text for term in PRODUCT_ACTION_TERMS):
        score += 20
        hits.append("产品/功能/工具/平台动作")

    if rejects:
        return "excluded", score, hits, rejects
    if any(term in text for term in PRIMARY_ALI) and any(term in text for term in PRODUCT_ACTION_TERMS):
        return "preferred", max(score, 80), hits, rejects
    if any(term in text for term in DOMESTIC_MAJORS) and any(term in text for term in PRODUCT_ACTION_TERMS):
        return "preferred", max(score, 72), hits, rejects
    if score >= 70:
        return "preferred", score, hits, rejects
    if score >= 35:
        return "lead", score, hits, rejects
    return "needs_review", score, hits, ["主体重要性不足，需人工确认"]


def reason_from_hits(category: str, hits: List[str], rejects: List[str]) -> str:
    if rejects:
        return "；".join(rejects)
    if hits:
        prefix = {
            "preferred": "符合优先级",
            "lead": "可作为备选线索",
            "needs_review": "待确认",
        }.get(category, "规则判断")
        return f"{prefix}：" + "、".join(hits)
    return "规则未给出明确理由"
