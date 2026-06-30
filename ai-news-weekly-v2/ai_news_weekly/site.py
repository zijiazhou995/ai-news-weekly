import html
import json
from pathlib import Path
from typing import Any, Dict, List

from .utils import write_json


def generate_site(site_dir: Path, week_data: Dict[str, Any], weeks_index_path: Path) -> None:
    site_dir.mkdir(parents=True, exist_ok=True)
    week_file = site_dir / "weeks" / f"{week_data['week_id']}.json"
    write_json(week_file, week_data)

    weeks = load_weeks_index(weeks_index_path)
    weeks = [w for w in weeks if w["week_id"] != week_data["week_id"]]
    weeks.insert(
        0,
        {
            "week_id": week_data["week_id"],
            "label": week_data["label"],
            "start_date": week_data["start_date"],
            "end_date": week_data["end_date"],
            "generated_at": week_data["generated_at"],
        },
    )
    weeks.sort(key=lambda item: item["end_date"], reverse=True)
    write_json(weeks_index_path, weeks)
    write_json(site_dir / "weeks.json", weeks)
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
    (site_dir / "index.html").write_text(render_index_html(weeks, week_data), encoding="utf-8")
    (site_dir / "app.js").write_text(render_app_js(), encoding="utf-8")
    (site_dir / "styles.css").write_text(render_css(), encoding="utf-8")
    (site_dir / "favicon.svg").write_text(render_favicon_svg(), encoding="utf-8")


def load_weeks_index(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def render_index_html(weeks: List[Dict[str, Any]], current: Dict[str, Any]) -> str:
    initial_week = html.escape(current["week_id"])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI 资讯周报</title>
  <link rel="icon" href="./favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="./styles.css">
</head>
<body>
  <header class="hero">
    <nav class="topbar">
      <div class="brand">AI News Weekly</div>
      <div class="source">AIbase-first</div>
    </nav>
    <section class="hero-inner">
      <p class="eyebrow">每周四更新</p>
      <h1>本周 AI 资讯</h1>
      <p class="subtitle">聚焦大厂、平台型公司与重要 AI 产品的新产品、新功能、新工具和新接入能力。</p>
      <div id="week-tabs" class="week-tabs" aria-label="周报列表"></div>
    </section>
  </header>
  <main class="content">
    <section class="week-summary">
      <div>
        <p class="eyebrow dark">当前周报</p>
        <h2 id="week-title">加载中</h2>
      </div>
      <div id="week-meta" class="week-meta"></div>
    </section>
    <section class="columns">
      <div>
        <h3>更符合要求</h3>
        <div id="preferred-list" class="card-list"></div>
      </div>
      <div>
        <h3>备选线索</h3>
        <div id="lead-list" class="card-list"></div>
      </div>
    </section>
    <section class="review">
      <h3>待确认 / 排除原因</h3>
      <div id="review-list" class="review-list"></div>
    </section>
  </main>
  <script>window.INITIAL_WEEK = "{initial_week}";</script>
  <script src="./app.js"></script>
</body>
</html>
"""


def render_app_js() -> str:
    return r"""const state = { weeks: [], current: null };

async function loadWeeks() {
  const res = await fetch('./weeks.json', { cache: 'no-store' });
  state.weeks = await res.json();
  const target = window.INITIAL_WEEK || state.weeks[0]?.week_id;
  await loadWeek(target);
  renderTabs();
}

async function loadWeek(weekId) {
  const res = await fetch(`./weeks/${weekId}.json`, { cache: 'no-store' });
  state.current = await res.json();
  window.INITIAL_WEEK = weekId;
  renderWeek();
  renderTabs();
}

function renderTabs() {
  const wrap = document.querySelector('#week-tabs');
  wrap.innerHTML = '';
  state.weeks.forEach(week => {
    const button = document.createElement('button');
    button.textContent = week.label;
    button.className = week.week_id === window.INITIAL_WEEK ? 'active' : '';
    button.addEventListener('click', () => loadWeek(week.week_id));
    wrap.appendChild(button);
  });
}

function renderWeek() {
  const week = state.current;
  document.querySelector('#week-title').textContent = `${week.label} AI 资讯`;
  document.querySelector('#week-meta').innerHTML = `
    <span>${week.start_date} 至 ${week.end_date}</span>
    <span>原始候选 ${week.raw_count} 条</span>
    <span>生成时间 ${week.generated_at}</span>`;
  renderCards('#preferred-list', week.preferred);
  renderCards('#lead-list', week.leads);
  renderReview(week);
}

function renderCards(selector, items) {
  const wrap = document.querySelector(selector);
  wrap.innerHTML = '';
  if (!items.length) {
    wrap.innerHTML = '<p class="empty">本周暂无通过校验的内容。</p>';
    return;
  }
  items.forEach(item => {
    const article = item.article;
    const card = document.createElement('article');
    card.className = 'news-card';
    card.innerHTML = `
      <div class="date">${escapeHtml(article.date)}</div>
      <h4>${escapeHtml(article.title)}</h4>
      <p>${escapeHtml(item.summary)}</p>
      <div class="card-footer">
        <span>${escapeHtml(item.reason)}</span>
        <a href="${article.url}" target="_blank" rel="noreferrer">详情页</a>
      </div>`;
    wrap.appendChild(card);
  });
}

function renderReview(week) {
  const wrap = document.querySelector('#review-list');
  const items = [
    ...week.needs_review.map(item => ({ label: '待确认', item })),
    ...week.excluded.map(item => ({ label: '已排除', item })),
  ];
  wrap.innerHTML = '';
  if (!items.length) {
    wrap.innerHTML = '<p class="empty">没有待确认或排除项。</p>';
    return;
  }
  items.forEach(({ label, item }) => {
    const article = item.article;
    const row = document.createElement('article');
    row.className = 'review-row';
    row.innerHTML = `
      <span>${label}</span>
      <strong>${escapeHtml(article.date)} ${escapeHtml(article.title)}</strong>
      <p>${escapeHtml([item.reason, ...(item.verifier_reasons || [])].filter(Boolean).join('；'))}</p>
      <a href="${article.url}" target="_blank" rel="noreferrer">查看原文</a>`;
    wrap.appendChild(row);
  });
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
}

loadWeeks().catch(error => {
  document.querySelector('#week-title').textContent = '加载失败';
  document.querySelector('#week-meta').textContent = error.message;
});
"""


def render_css() -> str:
    return r""":root {
  color-scheme: light;
  --ink: #111827;
  --muted: #657084;
  --line: #e5e7eb;
  --blue: #2563eb;
  --cyan: #08a6c7;
  --bg: #f5f7fb;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--ink);
}

.hero {
  min-height: 340px;
  color: white;
  background:
    radial-gradient(circle at 20% 10%, rgba(8, 166, 199, .45), transparent 28%),
    linear-gradient(135deg, #070b18 0%, #111827 48%, #0a2433 100%);
}

.topbar, .hero-inner, .content {
  width: min(1120px, calc(100% - 32px));
  margin: 0 auto;
}

.topbar {
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: rgba(255, 255, 255, .76);
}

.brand {
  color: white;
  font-weight: 800;
  letter-spacing: 0;
}

.source {
  border: 1px solid rgba(255, 255, 255, .22);
  border-radius: 999px;
  padding: 7px 12px;
  font-size: 13px;
}

.hero-inner {
  padding: 42px 0 44px;
}

.eyebrow {
  margin: 0 0 12px;
  color: #7dd3fc;
  font-size: 13px;
  font-weight: 700;
}

.eyebrow.dark { color: var(--cyan); }

h1 {
  margin: 0;
  font-size: clamp(42px, 7vw, 76px);
  line-height: 1;
  letter-spacing: 0;
}

.subtitle {
  max-width: 720px;
  margin: 22px 0 28px;
  color: rgba(255, 255, 255, .78);
  font-size: 18px;
  line-height: 1.7;
}

.week-tabs {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.week-tabs button {
  border: 1px solid rgba(255, 255, 255, .24);
  border-radius: 8px;
  background: rgba(255, 255, 255, .08);
  color: white;
  padding: 10px 14px;
  cursor: pointer;
}

.week-tabs button.active {
  background: white;
  color: #0f172a;
}

.content {
  padding: 34px 0 56px;
}

.week-summary {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: end;
  margin-bottom: 24px;
}

h2, h3, h4 {
  margin: 0;
  letter-spacing: 0;
}

h2 { font-size: 30px; }
h3 { font-size: 20px; margin-bottom: 14px; }
h4 { font-size: 18px; line-height: 1.45; }

.week-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--muted);
  font-size: 14px;
  text-align: right;
}

.columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 22px;
}

.card-list, .review-list {
  display: grid;
  gap: 14px;
}

.news-card {
  background: white;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  box-shadow: 0 12px 30px rgba(15, 23, 42, .06);
}

.date {
  color: var(--blue);
  font-weight: 800;
  font-size: 13px;
  margin-bottom: 8px;
}

.news-card p {
  color: #374151;
  line-height: 1.72;
  margin: 12px 0 16px;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: center;
  color: var(--muted);
  font-size: 13px;
}

a {
  color: var(--blue);
  text-decoration: none;
  font-weight: 700;
  white-space: nowrap;
}

.review {
  margin-top: 34px;
}

.review-row {
  background: white;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px 16px;
}

.review-row span {
  display: inline-block;
  margin-bottom: 8px;
  color: #b45309;
  font-size: 13px;
  font-weight: 800;
}

.review-row strong {
  display: block;
}

.review-row p {
  margin: 8px 0;
  color: var(--muted);
  line-height: 1.6;
}

.empty {
  color: var(--muted);
  background: rgba(255, 255, 255, .62);
  border: 1px dashed var(--line);
  border-radius: 8px;
  padding: 18px;
}

@media (max-width: 800px) {
  .columns, .week-summary {
    grid-template-columns: 1fr;
    display: grid;
  }

  .week-meta {
    text-align: left;
  }

  .card-footer {
    align-items: flex-start;
    flex-direction: column;
  }
}
"""


def render_favicon_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#111827"/>
  <path d="M18 42h28M20 36l6-16h12l6 16M25 30h14" fill="none" stroke="#7dd3fc" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""
