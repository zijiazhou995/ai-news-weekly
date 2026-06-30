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
  <main class="shell">
    <section id="home-view" class="view home-view">
      <header class="home-hero">
        <div class="mini-badge">每周四更新</div>
        <h1>AI 资讯周报</h1>
        <p>点开一个日期盒子，查看那一周筛选后的 AI 产品与平台动态。</p>
      </header>
      <section class="week-board" aria-label="周报日期列表">
        <div id="week-cards" class="week-cards"></div>
      </section>
    </section>

    <section id="detail-view" class="view detail-view" hidden>
      <button id="back-home" class="back-button" type="button">返回</button>
      <header class="detail-hero">
        <div class="mini-badge">本周 AI 资讯</div>
        <h2 id="week-title">加载中</h2>
        <p id="week-meta"></p>
      </header>

      <section class="news-section">
        <div class="section-heading">
          <h3>符合要求</h3>
          <span id="preferred-count"></span>
        </div>
        <div id="preferred-list" class="horizontal-list"></div>
      </section>

      <section class="news-section">
        <div class="section-heading">
          <h3>备选</h3>
          <span id="lead-count"></span>
        </div>
        <div id="lead-list" class="horizontal-list"></div>
      </section>

      <section class="news-section other-section">
        <div class="section-heading">
          <h3>其他</h3>
          <span id="other-count"></span>
        </div>
        <div id="other-list" class="other-list"></div>
      </section>
    </section>
  </main>
  <script>window.INITIAL_WEEK = "{initial_week}";</script>
  <script src="./app.js"></script>
</body>
</html>
"""


def render_app_js() -> str:
    return r"""const state = { weeks: [], current: null, counts: new Map() };

async function loadWeeks() {
  const res = await fetch('./weeks.json', { cache: 'no-store' });
  state.weeks = await res.json();
  await preloadCounts();
  renderHome();

  const hashWeek = new URLSearchParams(window.location.hash.replace(/^#\/?/, '')).get('week');
  if (hashWeek) {
    await openWeek(hashWeek);
  }
}

async function loadWeek(weekId) {
  const res = await fetch(`./weeks/${weekId}.json`, { cache: 'no-store' });
  return await res.json();
}

async function preloadCounts() {
  await Promise.all(state.weeks.map(async week => {
    try {
      const data = await loadWeek(week.week_id);
      state.counts.set(week.week_id, {
        preferred: data.preferred.length,
        leads: data.leads.length,
        other: data.needs_review.length,
      });
    } catch {
      state.counts.set(week.week_id, { preferred: 0, leads: 0, other: 0 });
    }
  }));
}

function renderHome() {
  const wrap = document.querySelector('#week-cards');
  wrap.innerHTML = '';
  state.weeks.forEach(week => {
    const counts = state.counts.get(week.week_id) || { preferred: 0, leads: 0, other: 0 };
    const button = document.createElement('button');
    button.className = 'week-card';
    button.type = 'button';
    button.innerHTML = `
      <span class="card-sticker">周报</span>
      <strong>${escapeHtml(formatLabel(week.label))}</strong>
      <span>${escapeHtml(formatDateRange(week))}</span>
      <small>${counts.preferred} 条符合 · ${counts.leads} 条备选 · ${counts.other} 条其他</small>`;
    button.addEventListener('click', () => openWeek(week.week_id));
    wrap.appendChild(button);
  });
}

async function openWeek(weekId) {
  state.current = await loadWeek(weekId);
  window.location.hash = `week=${encodeURIComponent(weekId)}`;
  document.querySelector('#home-view').hidden = true;
  document.querySelector('#detail-view').hidden = false;
  renderWeek();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showHome() {
  document.querySelector('#detail-view').hidden = true;
  document.querySelector('#home-view').hidden = false;
  window.location.hash = '';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function renderWeek() {
  const week = state.current;
  document.querySelector('#week-title').textContent = `${formatLabel(week.label)} AI 资讯`;
  document.querySelector('#week-meta').textContent = `${week.start_date} 至 ${week.end_date}`;
  document.querySelector('#preferred-count').textContent = `${week.preferred.length} 条`;
  document.querySelector('#lead-count').textContent = `${week.leads.length} 条`;
  document.querySelector('#other-count').textContent = `${week.needs_review.length} 条`;
  renderNewsCards('#preferred-list', week.preferred, '符合要求');
  renderNewsCards('#lead-list', week.leads, '备选');
  renderOther(week.needs_review);
}

function renderNewsCards(selector, items, label) {
  const wrap = document.querySelector(selector);
  wrap.innerHTML = '';
  if (!items.length) {
    wrap.innerHTML = '<p class="empty">这一栏暂时空空的。</p>';
    return;
  }
  items.forEach(item => {
    const article = item.article;
    const card = document.createElement('article');
    card.className = 'news-card';
    card.innerHTML = `
      <div class="tag-row"><span>${escapeHtml(label)}</span><span>${escapeHtml(article.date)}</span></div>
      <h4>${escapeHtml(article.title)}</h4>
      <p>${escapeHtml(item.summary)}</p>
      <div class="card-footer">
        <span>${escapeHtml(shortReason(item.reason))}</span>
        <a href="${article.url}" target="_blank" rel="noreferrer">查看原文</a>
      </div>`;
    wrap.appendChild(card);
  });
}

function renderOther(items) {
  const wrap = document.querySelector('#other-list');
  wrap.innerHTML = '';
  if (!items.length) {
    wrap.innerHTML = '<p class="empty">没有其他待看的线索。</p>';
    return;
  }
  items.forEach(item => {
    const article = item.article;
    const row = document.createElement('article');
    row.className = 'other-card';
    row.innerHTML = `
      <strong>${escapeHtml(article.date)} ${escapeHtml(article.title)}</strong>
      <p>${escapeHtml([item.reason, ...(item.verifier_reasons || [])].filter(Boolean).join('；'))}</p>
      <a href="${article.url}" target="_blank" rel="noreferrer">查看原文</a>`;
    wrap.appendChild(row);
  });
}

function formatLabel(label) {
  return String(label || '').replace('-', '～');
}

function formatDateRange(week) {
  return `${week.start_date} / ${week.end_date}`;
}

function shortReason(reason) {
  return String(reason || '').replace(/^符合优先级：/, '').replace(/^可作为备选线索：/, '');
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
}

document.querySelector('#back-home').addEventListener('click', showHome);

loadWeeks().catch(error => {
  document.querySelector('#week-cards').innerHTML = `<p class="empty">加载失败：${escapeHtml(error.message)}</p>`;
});
"""


def render_css() -> str:
    return r""":root {
  color-scheme: light;
  --ink: #243042;
  --muted: #768196;
  --line: #e8e2d9;
  --blue: #6ea8fe;
  --mint: #9de7d7;
  --sun: #ffe59a;
  --pink: #ffc7d6;
  --paper: #fffdf8;
  --bg: #faf7ef;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: ui-rounded, "SF Pro Rounded", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--ink);
}

.shell {
  width: min(1180px, calc(100% - 32px));
  margin: 0 auto;
  padding: 44px 0 64px;
}

.view[hidden] {
  display: none;
}

.home-hero,
.detail-hero {
  position: relative;
  padding: 34px;
  border: 2px solid #2f3a4d;
  border-radius: 28px;
  background:
    linear-gradient(120deg, rgba(255, 229, 154, .72), rgba(157, 231, 215, .6)),
    var(--paper);
  box-shadow: 10px 10px 0 rgba(47, 58, 77, .12);
  overflow: hidden;
}

.home-hero::after,
.detail-hero::after {
  content: "";
  position: absolute;
  right: 34px;
  top: 32px;
  width: 86px;
  height: 86px;
  border-radius: 50%;
  background:
    radial-gradient(circle at center, #fff 0 18%, transparent 19%),
    conic-gradient(from 15deg, var(--pink), var(--sun), var(--mint), var(--blue), var(--pink));
  opacity: .9;
}

.mini-badge {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 6px 12px;
  border: 2px solid #2f3a4d;
  border-radius: 999px;
  background: white;
  color: #2f3a4d;
  font-size: 13px;
  font-weight: 800;
}

h1, h2, h3, h4, p {
  letter-spacing: 0;
}

h1 {
  margin: 18px 0 12px;
  font-size: clamp(42px, 8vw, 82px);
  line-height: .96;
}

.home-hero p,
.detail-hero p {
  max-width: 680px;
  margin: 0;
  color: #596579;
  font-size: 18px;
  line-height: 1.7;
}

.week-board {
  margin-top: 30px;
}

.week-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 18px;
}

.week-card {
  min-height: 172px;
  border: 2px solid #2f3a4d;
  border-radius: 24px;
  background: var(--paper);
  color: var(--ink);
  padding: 20px;
  text-align: left;
  cursor: pointer;
  box-shadow: 7px 7px 0 rgba(47, 58, 77, .1);
  transition: transform .16s ease, box-shadow .16s ease;
}

.week-card:nth-child(3n + 1) { background: #fff8d7; }
.week-card:nth-child(3n + 2) { background: #eafff9; }
.week-card:nth-child(3n + 3) { background: #fff0f5; }

.week-card:hover {
  transform: translateY(-4px);
  box-shadow: 10px 10px 0 rgba(47, 58, 77, .14);
}

.week-card strong {
  display: block;
  margin: 18px 0 8px;
  font-size: 34px;
  line-height: 1;
}

.week-card span,
.week-card small {
  display: block;
  color: var(--muted);
}

.card-sticker {
  width: fit-content;
  padding: 5px 10px;
  border: 2px solid #2f3a4d;
  border-radius: 999px;
  background: white;
  color: #2f3a4d !important;
  font-size: 12px;
  font-weight: 900;
}

.back-button {
  margin: 0 0 18px;
  border: 2px solid #2f3a4d;
  border-radius: 999px;
  background: white;
  color: #2f3a4d;
  padding: 9px 14px;
  font-weight: 800;
  cursor: pointer;
}

h2 {
  margin: 16px 0 10px;
  font-size: clamp(34px, 6vw, 58px);
  line-height: 1;
}

.news-section {
  margin-top: 34px;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.section-heading h3 {
  margin: 0;
  font-size: 24px;
}

.section-heading span {
  color: var(--muted);
  font-weight: 800;
}

.horizontal-list {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(280px, 360px);
  gap: 16px;
  overflow-x: auto;
  padding: 0 0 14px;
  scroll-snap-type: x proximity;
}

.news-card {
  min-height: 330px;
  display: flex;
  flex-direction: column;
  scroll-snap-align: start;
  background: white;
  border: 2px solid #2f3a4d;
  border-radius: 22px;
  padding: 18px;
  box-shadow: 7px 7px 0 rgba(47, 58, 77, .1);
}

.tag-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: var(--muted);
  font-weight: 800;
  font-size: 13px;
}

.tag-row span:first-child {
  padding: 4px 9px;
  border-radius: 999px;
  background: #e8f4ff;
  color: #2563a8;
}

h4 {
  margin: 16px 0 0;
  font-size: 19px;
  line-height: 1.45;
}

.news-card p {
  color: #495569;
  line-height: 1.7;
  margin: 12px 0 16px;
  flex: 1;
}

.card-footer {
  display: flex;
  flex-direction: column;
  gap: 14px;
  align-items: flex-start;
  color: var(--muted);
  font-size: 13px;
}

a {
  color: #2563a8;
  text-decoration: none;
  font-weight: 700;
}

.card-footer a,
.other-card a {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 7px 12px;
  border-radius: 999px;
  background: #2f3a4d;
  color: white;
}

.other-section {
  margin-top: 26px;
}

.other-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}

.other-card {
  background: rgba(255, 255, 255, .74);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 14px;
}

.other-card strong {
  display: block;
  line-height: 1.45;
}

.other-card p {
  margin: 8px 0;
  color: var(--muted);
  line-height: 1.6;
  font-size: 14px;
}

.empty {
  color: var(--muted);
  background: rgba(255, 255, 255, .68);
  border: 2px dashed var(--line);
  border-radius: 18px;
  padding: 18px;
}

@media (max-width: 800px) {
  .shell {
    width: min(100% - 22px, 1180px);
    padding-top: 18px;
  }

  .home-hero,
  .detail-hero {
    padding: 24px;
    border-radius: 24px;
  }

  .home-hero::after,
  .detail-hero::after {
    width: 58px;
    height: 58px;
    right: 18px;
    top: 18px;
  }

  .horizontal-list {
    grid-auto-columns: minmax(260px, 86vw);
  }
}
"""


def render_favicon_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#111827"/>
  <path d="M18 42h28M20 36l6-16h12l6 16M25 30h14" fill="none" stroke="#7dd3fc" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""
