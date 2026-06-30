const state = { weeks: [], current: null };

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
