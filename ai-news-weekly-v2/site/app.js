const state = { weeks: [], current: null, counts: new Map() };

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
