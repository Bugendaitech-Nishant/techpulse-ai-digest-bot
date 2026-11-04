/**
 * TechPulse live feed controller.
 * Ranked list and split view, filters kept in the URL, four data states
 * (loading, empty, error, full) and readings drawn from /api/insights.
 * Shared helpers (escapeHtml, toasts, quota, harvest, export) live in shell.js.
 */

const CATEGORY_LABELS = {
  todo: 'To do', doing: 'In progress', curated: 'All signal', 'Must Read': 'Must read',
  Inspiration: 'Inspiration', handled: 'Handled', Skip: 'Safe to ignore',
};
const STEP_ORDER = ['Patch', 'Try', 'Evaluate', 'Read', 'Watch'];
const STEP_HEADINGS = { Patch: 'Needs action', Try: 'Try this', Evaluate: 'Worth comparing', Read: 'Worth knowing', Watch: 'Keep an eye on' };
const VALID_CATEGORIES = Object.keys(CATEGORY_LABELS);

const state = {
  digest: null,
  availableDigests: [],
  selectedDate: 'latest',
  stats: null,
  insights: null,
  ratings: {}, // url -> 1 useful, -1 not useful
  feedback: { persistent: false, write_requires_key: false },
  viewMode: 'grid', // 'grid' (ranked list) | 'cockpit' (split view)
  activeCategory: null, // chosen after the first load: To do when something needs someone, else All signal
  activeSource: 'all',
  activeTopic: 'all',
  searchQuery: '',
  selectedIndex: 0,
  filteredItems: [],
};

// ─── URL state ─────────────────────────────────────────────────────────────

function readUrlState() {
  const p = new URLSearchParams(window.location.search);
  const cat = p.get('cat');
  if (cat && VALID_CATEGORIES.includes(cat)) state.activeCategory = cat;
  state.activeSource = p.get('src') || 'all';
  state.activeTopic = p.get('topic') || 'all';
  state.searchQuery = (p.get('q') || '').toLowerCase().trim();
  state.selectedDate = p.get('date') || 'latest';
  state.viewMode = p.get('view') === 'split' ? 'cockpit' : 'grid';
}

function writeUrlState() {
  const p = new URLSearchParams();
  if (state.activeCategory) p.set('cat', state.activeCategory);
  if (state.activeSource !== 'all') p.set('src', state.activeSource);
  if (state.activeTopic !== 'all') p.set('topic', state.activeTopic);
  if (state.searchQuery) p.set('q', state.searchQuery);
  if (state.selectedDate !== 'latest') p.set('date', state.selectedDate);
  if (state.viewMode === 'cockpit') p.set('view', 'split');
  const qs = p.toString();
  history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
}

/** Reflect state into the controls so a shared link opens exactly as it was saved. */
function syncControls() {
  document.getElementById('search-input').value = state.searchQuery;
  document.querySelectorAll('.seg-btn').forEach((b) => b.classList.toggle('is-active', b.dataset.category === state.activeCategory));
  renderNameButton();
  const cockpit = state.viewMode === 'cockpit';
  document.getElementById('view-cockpit-btn').classList.toggle('is-active', cockpit);
  document.getElementById('view-cards-btn').classList.toggle('is-active', !cockpit);
  document.getElementById('keyboard-hint').style.display = cockpit ? 'flex' : 'none';
}

// ─── Initialization ────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  readUrlState();
  syncControls();
  setupHandlers();
  initHarvest(loadData);
  loadData();
  // Teammates act while this page is open: refresh their changes quietly.
  setInterval(refreshTriage, 60000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshTriage(); });
});

async function refreshTriage() {
  const editing = document.activeElement && ['TEXTAREA', 'INPUT'].includes(document.activeElement.tagName);
  if (document.hidden || editing || document.getElementById('grid-modal')) return;
  if (await loadTriage()) rerenderAll();
}

function rerenderAll() {
  if (!state.digest) return;
  renderReadings();
  renderCategoryBadges();
  renderSpectrumRail();
  renderTopicRail();
  renderContent();
}

function setupHandlers() {
  const searchInput = document.getElementById('search-input');
  searchInput.addEventListener('input', (e) => {
    state.searchQuery = e.target.value.toLowerCase().trim();
    state.selectedIndex = 0;
    writeUrlState();
    renderContent();
  });

  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      searchInput.focus();
      return;
    }

    const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement && document.activeElement.tagName);
    if (typing) {
      if (e.key === 'Escape') document.activeElement.blur();
      return;
    }

    if (e.key === 'Escape') closeModal();

    if (e.key === 'ArrowDown' || e.key === 'j') {
      e.preventDefault();
      moveSelection(1);
    } else if (e.key === 'ArrowUp' || e.key === 'k') {
      e.preventDefault();
      moveSelection(-1);
    } else if ((e.key === 'Enter' || e.key === 'o') && document.activeElement === document.body) {
      const cur = state.filteredItems[state.selectedIndex];
      if (cur && cur.url) window.open(cur.url, '_blank', 'noopener');
    }
  });

  document.getElementById('date-select').addEventListener('change', async (e) => {
    state.selectedDate = e.target.value;
    state.selectedIndex = 0;
    writeUrlState();
    await loadDigest();
  });

  document.getElementById('btn-export').addEventListener('click', () => {
    const date = state.digest && state.digest.date ? state.digest.date : new Date().toISOString().split('T')[0];
    downloadMarkdown(date);
  });

  document.querySelectorAll('.seg-btn').forEach((btn) => {
    btn.addEventListener('click', () => switchCategoryTab(btn.dataset.category));
  });

  document.getElementById('kpi-card-open').addEventListener('click', () => switchCategoryTab('todo'));
  document.getElementById('kpi-card-doing').addEventListener('click', () => switchCategoryTab('doing'));
  document.getElementById('kpi-card-done').addEventListener('click', () => switchCategoryTab('handled'));
  document.getElementById('kpi-card-must-read').addEventListener('click', () => switchCategoryTab('Must Read'));

  document.getElementById('btn-brief').addEventListener('click', copyBrief);
  document.getElementById('btn-name').addEventListener('click', async () => { if (await askName()) rerenderAll(); });
  document.addEventListener('triage-changed', () => { rerenderAll(); refreshOpenPanel(); });
  document.addEventListener('click', (e) => {
    const menu = document.getElementById('admin-menu');
    if (menu && menu.open && !menu.contains(e.target)) menu.open = false;
  });

  document.getElementById('view-cards-btn').addEventListener('click', () => setViewMode('grid'));
  document.getElementById('view-cockpit-btn').addEventListener('click', () => setViewMode('cockpit'));
}

function setViewMode(mode) {
  state.viewMode = mode;
  syncControls();
  writeUrlState();
  renderContent();
}

function switchCategoryTab(category) {
  state.activeCategory = category;
  state.selectedIndex = 0;
  syncControls();
  writeUrlState();
  renderSpectrumRail();
  renderTopicRail();
  renderContent();
}

/** The brief a team pastes into chat. Falls back to a box the reader can copy from. */
async function copyBrief() {
  if (!state.digest) { showToast('There is no digest to brief on yet.'); return; }
  let markdown;
  try {
    markdown = (await getJson(`/api/brief?date=${encodeURIComponent(state.digest.date)}`, 20000)).markdown;
  } catch (err) {
    showToast('Could not build the brief.');
    return;
  }
  try {
    await navigator.clipboard.writeText(markdown);
    showToast('Brief copied. Paste it into chat or your standup notes.');
  } catch (err) {
    openModal({ title: 'Brief' }, null, `<h2 class="inspector-title">Brief</h2><textarea class="field note-field" rows="14" readonly aria-label="Brief">${escapeHtml(markdown)}</textarea>`);
    const box = document.querySelector('#grid-modal textarea');
    if (box) box.select();
  }
}

// ─── Data loading ──────────────────────────────────────────────────────────

function setBusy(busy) {
  document.getElementById('content-container').setAttribute('aria-busy', busy ? 'true' : 'false');
}

async function loadData() {
  const container = document.getElementById('content-container');
  const wake = document.getElementById('wake-note');
  const wakeTimer = setTimeout(() => { wake.hidden = false; }, 3000);
  setBusy(true);

  try {
    const [stats, digests, insights, feedback] = await Promise.all([
      refreshQuota(),
      getJson('/api/digests').catch(() => []),
      getJson('/api/insights').catch(() => null),
      getJson('/api/feedback').catch(() => null),
      loadTriage(),
    ]);
    state.stats = stats;
    if (feedback) {
      state.ratings = feedback.ratings || {};
      state.feedback = feedback;
    }
    state.availableDigests = Array.isArray(digests) ? digests : [];
    state.insights = insights;
    await loadDigest();
  } catch (err) {
    console.error('Failed to load the digest:', err);
    renderError(container, () => loadData());
  } finally {
    clearTimeout(wakeTimer);
    wake.hidden = true;
    setBusy(false);
  }
}

async function loadDigest() {
  const container = document.getElementById('content-container');
  try {
    const path = state.selectedDate === 'latest' ? '/api/digest/latest' : `/api/digest/${encodeURIComponent(state.selectedDate)}`;
    state.digest = await getJson(path);
  } catch (err) {
    state.digest = null;
    if (String(err.message).includes('404')) {
      renderEmpty(container, 'No digest yet', 'Run a harvest to collect and rank the first one.');
    } else {
      renderError(container, () => loadDigest());
    }
    populateDateSelect();
    renderReadings();
    return;
  }
  populateDateSelect();
  if (!state.activeCategory) state.activeCategory = defaultCategory();
  syncControls();
  writeUrlState();
  rerenderAll();
}

/** Open on what needs doing; fall back to everything when the queue is empty. */
function defaultCategory() {
  const items = (state.digest && state.digest.items) || [];
  return items.some((i) => inCategory(i, 'todo')) ? 'todo' : 'curated';
}

function populateDateSelect() {
  const select = document.getElementById('date-select');
  select.innerHTML = '<option value="latest">Latest digest</option>';
  state.availableDigests.forEach((d) => {
    const opt = document.createElement('option');
    opt.value = d.date;
    opt.textContent = `${d.date}, ${d.total_curated || 0} curated`;
    select.appendChild(opt);
  });
  select.value = state.selectedDate;
  if (select.value !== state.selectedDate) select.value = 'latest';
}

// ─── Readings (real figures only) ──────────────────────────────────────────

function renderReadings() {
  const items = (state.digest && state.digest.items) || [];
  const kept = items.filter((i) => i.category !== 'Skip');
  const count = (cat) => items.filter((i) => inCategory(i, cat)).length;

  const doing = {};
  kept.filter((i) => triageOf(i).status === 'doing').forEach((i) => {
    const who = triageOf(i).owner || 'someone';
    doing[who] = (doing[who] || 0) + 1;
  });
  const done = kept.filter((i) => triageOf(i).status === 'done').length;
  const dismissed = kept.filter((i) => triageOf(i).status === 'dismissed').length;
  const have = !!state.digest;

  document.getElementById('kpi-open').textContent = have ? count('todo') : '--';
  document.getElementById('kpi-doing').textContent = have ? count('doing') : '--';
  document.getElementById('kpi-doing-note').textContent = Object.keys(doing).length
    ? Object.entries(doing).sort((a, b) => b[1] - a[1]).map(([who, n]) => `${who} ${n}`).join(' · ')
    : 'nobody has taken anything yet';
  document.getElementById('kpi-done').textContent = have ? done + dismissed : '--';
  document.getElementById('kpi-done-note').textContent = `${done} done, ${dismissed} not for us`;
  document.getElementById('kpi-must-read').textContent = have ? count('Must Read') : '--';
  document.getElementById('kpi-must-note').textContent = kept.length ? `of ${kept.length} curated` : 'of the curated set';

  renderFeedbackNote();
  renderColophon();
  const sub = document.getElementById('page-sub');
  const title = document.getElementById('page-title');
  if (state.digest) {
    title.textContent = state.selectedDate === 'latest' ? 'Today’s digest' : `Digest of ${state.digest.date}`;
    const from = state.digest.total_harvested ? ` from ${state.digest.total_harvested} harvested` : '';
    const when = state.digest.created_at ? `, built ${relativeTime(state.digest.created_at)}` : '';
    sub.textContent = `${state.digest.date}: ${kept.length} curated${from}${when}.`;
  } else {
    sub.textContent = 'No digest to show.';
  }
}

/** How the digest was made: for whoever audits it, kept out of the way of the work. */
function renderColophon() {
  const parts = [];
  const model = state.stats && state.stats.llm_model;
  if (model) parts.push(`Curated by ${model.includes('/') ? model.split('/')[1] : model}`);
  if (state.digest && state.digest.ranking_backend) parts.push(`ranked by ${state.digest.ranking_backend} ${state.digest.ranking_version || ''}`.trim());
  const seen = state.insights ? state.insights.seen_in_window : (state.stats && state.stats.total_seen_urls);
  if (Number.isFinite(seen)) parts.push(`${seen} URLs tracked over 30 days`);
  if (state.digest) parts.push(triageState.persistent ? 'team status is saved to GitHub' : 'team status is kept on this server and resets if it restarts');
  document.getElementById('colophon').textContent = parts.join(' · ');
}

function renderCategoryBadges() {
  const items = (state.digest && state.digest.items) || [];
  const ids = { todo: 'count-todo', doing: 'count-doing', curated: 'count-curated', 'Must Read': 'count-must-read', Inspiration: 'count-inspiration', handled: 'count-handled', Skip: 'count-skip' };
  Object.entries(ids).forEach(([cat, id]) => {
    document.getElementById(id).textContent = items.filter((i) => inCategory(i, cat)).length;
  });
}

/** Which tab an item belongs to. Handled items stay in the category tabs, dimmed, so nothing vanishes. */
function inCategory(item, cat) {
  const status = triageOf(item).status;
  switch (cat) {
    case 'todo': return isActionable(item) && status === 'open';
    case 'doing': return item.category !== 'Skip' && status === 'doing';
    case 'handled': return item.category !== 'Skip' && (status === 'done' || status === 'dismissed');
    case 'curated': return item.category !== 'Skip';
    default: return item.category === cat;
  }
}

// ─── Source filter rail ────────────────────────────────────────────────────

function renderSpectrumRail() {
  const rail = document.getElementById('spectrum-rail');
  rail.innerHTML = '';
  if (!state.digest || !state.digest.items) return;

  const relevant = state.digest.items.filter((i) => inCategory(i, state.activeCategory));
  const counts = {};
  relevant.forEach((item) => { counts[item.source] = (counts[item.source] || 0) + 1; });
  if (state.activeSource !== 'all' && !counts[state.activeSource]) counts[state.activeSource] = 0;

  rail.appendChild(railLabel('Source'));
  rail.appendChild(createSpectrumPill('all', 'All sources', relevant.length));
  Object.keys(counts)
    .sort((a, b) => counts[b] - counts[a])
    .forEach((key) => rail.appendChild(createSpectrumPill(key, sourceName(key), counts[key])));
}

function railLabel(text) {
  const label = document.createElement('span');
  label.className = 'rail-label';
  label.textContent = text;
  return label;
}

/** Topics let a teammate follow only their area: security for one person, inference for another. */
function renderTopicRail() {
  const rail = document.getElementById('topic-rail');
  rail.innerHTML = '';
  if (!state.digest || !state.digest.items) return;

  const counts = {};
  state.digest.items.filter((i) => inCategory(i, state.activeCategory))
    .forEach((item) => (item.topics || []).forEach((t) => { counts[t] = (counts[t] || 0) + 1; }));
  if (state.activeTopic !== 'all' && !counts[state.activeTopic]) counts[state.activeTopic] = 0;
  const topics = Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a.localeCompare(b));
  if (!topics.length) return;

  rail.appendChild(railLabel('Topic'));
  rail.appendChild(createTopicPill('all', 'All topics', null));
  topics.slice(0, 12).concat(topics.slice(12).filter((t) => t === state.activeTopic))
    .forEach((t) => rail.appendChild(createTopicPill(t, t.replace(/-/g, ' '), counts[t])));
}

function createTopicPill(key, label, count) {
  const pill = document.createElement('button');
  pill.type = 'button';
  pill.className = `spectrum-pill ${state.activeTopic === key ? 'is-active' : ''}`;
  pill.setAttribute('aria-pressed', state.activeTopic === key ? 'true' : 'false');
  pill.dataset.topic = key;
  pill.innerHTML = `<span>${escapeHtml(label)}</span>${count === null ? '' : `<span class="spectrum-count">${count}</span>`}`;
  pill.addEventListener('click', () => {
    state.activeTopic = key;
    state.selectedIndex = 0;
    writeUrlState();
    renderTopicRail();
    renderContent();
  });
  return pill;
}

function createSpectrumPill(key, label, count) {
  const pill = document.createElement('button');
  pill.type = 'button';
  pill.className = `spectrum-pill ${state.activeSource === key ? 'is-active' : ''}`;
  pill.setAttribute('aria-pressed', state.activeSource === key ? 'true' : 'false');
  pill.innerHTML = `<span>${escapeHtml(label)}</span><span class="spectrum-count">${count}</span>`;
  pill.addEventListener('click', () => {
    state.activeSource = key;
    state.selectedIndex = 0;
    writeUrlState();
    renderSpectrumRail();
    renderTopicRail();
    renderContent();
  });
  return pill;
}

// ─── Filtering and rendering ───────────────────────────────────────────────

function computeFilteredItems() {
  if (!state.digest || !state.digest.items) return [];
  return state.digest.items.filter((item) => {
    if (!inCategory(item, state.activeCategory)) return false;
    if (state.activeSource !== 'all' && item.source !== state.activeSource) return false;
    if (state.activeTopic !== 'all' && !(item.topics || []).includes(state.activeTopic)) return false;
    if (state.searchQuery) {
      const text = `${item.title} ${item.summary} ${item.why_it_matters} ${item.next_step_detail} ${item.source} ${(item.topics || []).join(' ')} ${triageOf(item).owner} ${triageOf(item).note}`.toLowerCase();
      if (!state.searchQuery.split(/\s+/).every((word) => text.includes(word))) return false;
    }
    return true;
  }).sort((a, b) => stepRank(a) - stepRank(b)); // stable: keeps the ranking inside each group
}

function stepRank(item) {
  const i = STEP_ORDER.indexOf(item.next_step);
  return i === -1 ? STEP_ORDER.length : i;
}

function renderContent() {
  const container = document.getElementById('content-container');
  if (!state.digest) return;
  state.filteredItems = computeFilteredItems();

  if (state.filteredItems.length === 0) {
    const [title, body] = emptyMessage();
    renderEmpty(container, title, body, true);
    return;
  }
  if (state.selectedIndex >= state.filteredItems.length) state.selectedIndex = 0;

  if (state.viewMode === 'grid') renderListView(container);
  else renderSplitView(container);
}

function renderEmpty(container, title, body, withReset = false) {
  container.className = 'cards-grid-view';
  container.innerHTML = `
    <div class="state-panel">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(body)}</p>
      ${withReset ? '<button type="button" class="btn" id="btn-reset">Show all signal</button>' : ''}
    </div>`;
  const reset = document.getElementById('btn-reset');
  if (reset) reset.addEventListener('click', resetFilters);
}

/** What an empty tab means, so an empty queue reads as good news rather than a fault. */
function emptyMessage() {
  const filtered = state.searchQuery || state.activeSource !== 'all' || state.activeTopic !== 'all';
  if (filtered) return ['Nothing matches these filters', 'Clear the search, source or topic, or look at all signal.'];
  return {
    todo: ['Nothing is waiting on anyone', 'Every Patch, Try and Evaluate item today has an owner or was handled. Read the rest under All signal.'],
    doing: ['Nobody has taken anything yet', 'Take an item from To do and it shows here for the whole team.'],
    handled: ['Nothing handled yet', 'Items marked done, or not for us, collect here so they can be reopened.'],
  }[state.activeCategory] || ['Nothing here', 'Try another view.'];
}

function renderError(container, retry) {
  container.className = 'cards-grid-view';
  container.innerHTML = `
    <div class="state-panel is-error">
      <h3>The digest did not load</h3>
      <p>The server did not answer in time. If it was idle, it needs about 30 seconds to wake. Nothing is lost.</p>
      <button type="button" class="btn btn-primary" id="btn-retry">Try again</button>
    </div>`;
  document.getElementById('btn-retry').addEventListener('click', retry);
}

function resetFilters() {
  state.searchQuery = '';
  state.activeSource = 'all';
  state.activeTopic = 'all';
  state.activeCategory = 'curated';
  state.selectedIndex = 0;
  syncControls();
  writeUrlState();
  rerenderAll();
}

function renderListView(container) {
  container.className = 'cards-grid-view';
  container.innerHTML = '';
  const grouped = ['curated', 'todo'].includes(state.activeCategory) && new Set(state.filteredItems.map((i) => i.next_step)).size > 1;
  let lastStep = null;
  state.filteredItems.forEach((item, index) => {
    if (grouped && item.next_step !== lastStep) {
      lastStep = item.next_step;
      const h = document.createElement('h2');
      h.className = 'step-heading';
      h.textContent = STEP_HEADINGS[lastStep] || 'Worth knowing';
      container.appendChild(h);
    }
    container.appendChild(buildSignalCard(item, index));
  });
}

function renderSplitView(container) {
  container.className = 'cockpit-split-view';
  container.innerHTML = '';

  const feedPane = document.createElement('div');
  feedPane.className = 'scrollable-feed-pane';
  feedPane.setAttribute('role', 'list');
  state.filteredItems.forEach((item, index) => feedPane.appendChild(buildSignalCard(item, index)));

  const inspector = document.createElement('aside');
  inspector.className = 'sticky-inspector-pane';
  inspector.id = 'sticky-inspector';
  inspector.setAttribute('aria-label', 'Selected item');
  inspector.innerHTML = buildInspectorHtml(state.filteredItems[state.selectedIndex] || state.filteredItems[0]);

  container.appendChild(feedPane);
  container.appendChild(inspector);
}

function badgeClass(category) {
  return category === 'Must Read' ? 'must-read' : category === 'Inspiration' ? 'inspiration' : 'skip';
}

function categoryLabel(category) {
  return category === 'Must Read' ? 'Must Read' : category;
}

/** "5 h ago" from the source's own date; digests saved before dates were kept say so instead of guessing. */
function ageLabel(item) {
  return (item.published_at && relativeTime(item.published_at)) || 'date not recorded';
}

function metaLine(item) {
  const tags = [...(item.topics || []), ...(item.tags || [])].slice(0, 5).map((t) => `#${escapeHtml(String(t).replace(/\s+/g, '-'))}`).join(' ');
  return `${escapeHtml(ageLabel(item))}${tags ? ` · ${tags}` : ''}`;
}

function verificationLine(item) {
  if (item.verification === 'verified') return '<span class="check-mark">Checked against source</span>';
  if (item.verification === 'corrected') return '<span class="check-mark">Corrected against source</span>';
  if (item.verification === 'unverified') return `<span class="check-mark check-warn" title="${escapeHtml(item.verification_note)}">Not fully backed by source</span>`;
  return '';
}

function nextStepLine(item) {
  const story = item.story_id ? ` <button type="button" class="story-btn" data-story="${escapeHtml(item.story_id)}">Follow the story</button>` : '';
  if (item.category === 'Skip' || (!item.next_step_detail && !story)) return story ? `<p class="card-next">${story}</p>` : '';
  const detail = item.next_step_detail ? `<strong>${escapeHtml(item.next_step)}:</strong> ${escapeHtml(item.next_step_detail)}` : '';
  return `<p class="card-next">${detail}${story}</p>`;
}

async function openStory(storyId) {
  let items;
  try {
    items = (await getJson(`/api/story/${encodeURIComponent(storyId)}`)).items;
  } catch (err) {
    showToast('Could not load the story.');
    return;
  }
  const rows = items.map((i) => `
    <li>
      <span class="measured">${escapeHtml((i.published_at || i.digest_date || '').slice(0, 10))}</span>
      <a href="${escapeHtml(i.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(i.title)}</a>
      <p>${escapeHtml(i.next_step_detail || i.summary)}</p>
    </li>`).join('');
  openModal({ title: 'Story', url: '', summary: '' }, null, `<h2 class="inspector-title">The story so far</h2><ol class="story-list">${rows}</ol>`);
}

function buildSignalCard(item, index) {
  const card = document.createElement('div');
  card.setAttribute('role', 'listitem');
  const handled = ['done', 'dismissed'].includes(triageOf(item).status);
  card.className = `signal-card ${state.selectedIndex === index ? 'is-selected' : ''} ${item.category === 'Skip' ? 'is-skip' : ''} ${handled ? 'is-handled' : ''}`;
  card.tabIndex = 0;

  card.innerHTML = `
    <span class="card-rank">${String(index + 1).padStart(2, '0')}</span>
    <div class="card-main">
      <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" class="card-title">${escapeHtml(item.title)}</a>
      <p class="card-meta">${metaLine(item)}</p>
      <p class="card-desc">${escapeHtml(plainText(item.category === 'Skip' ? item.why_it_matters : item.summary))}</p>
      ${nextStepLine(item)}
      ${triageControls(item)}
      ${verificationLine(item)}
    </div>
    <div class="card-foot">
      <span class="badge-source">${escapeHtml(sourceName(item.source))}</span>
      <span class="score-badge ${badgeClass(item.category)}">${escapeHtml(categoryLabel(item.category))}</span>
      ${rateButtons(item.url)}
      <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" class="action-link">Open</a>
    </div>`;

  card.querySelectorAll('a').forEach((a) => a.addEventListener('click', (e) => e.stopPropagation()));

  const activate = () => {
    state.selectedIndex = index;
    if (state.viewMode === 'cockpit') {
      document.querySelectorAll('.signal-card').forEach((c) => c.classList.remove('is-selected'));
      card.classList.add('is-selected');
      const insp = document.getElementById('sticky-inspector');
      if (insp) insp.innerHTML = buildInspectorHtml(item);
    } else {
      openModal(item, card);
    }
  };
  card.addEventListener('click', (e) => {
    if (e.target.closest('.rate') || e.target.closest('.story-btn') || e.target.closest('.card-triage')) return; // acting on a row must not also open it
    activate();
  });
  card.addEventListener('keydown', (e) => {
    if (e.target !== card) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      activate();
    }
  });
  return card;
}

// ─── Inspector and quick reader ────────────────────────────────────────────

function buildInspectorHtml(item) {
  if (!item) return '<p class="empty-canvas">Select an item to read it here.</p>';
  return `
    <div class="inspector-header">
      <div class="inspector-meta">
        <span class="badge-source">${escapeHtml(sourceName(item.source))}</span>
        <span class="score-badge ${badgeClass(item.category)}">${escapeHtml(categoryLabel(item.category))}</span>
      </div>
      <h2 class="inspector-title">${escapeHtml(item.title)}</h2>
      <div class="inspector-actions">
        <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary">Open source</a>
        <button type="button" class="btn" data-copy="${escapeHtml(item.url)}">Copy link</button>
      </div>
      ${rateButtons(item.url)}
    </div>

    <div class="inspector-section team-section">
      <span class="inspector-heading">Team</span>
      ${triageControls(item) || '<p class="inspector-text">Filtered-out items are not triaged.</p>'}
      ${noteBox(item)}
    </div>

    <div class="inspector-section">
      <span class="inspector-heading">Summary</span>
      <p class="inspector-text">${escapeHtml(plainText(item.summary))}</p>
    </div>

    ${item.next_step_detail ? `
      <div class="inspector-section">
        <span class="inspector-heading">${escapeHtml(item.next_step)}</span>
        <p class="inspector-text">${escapeHtml(item.next_step_detail)}</p>
      </div>` : ''}

    ${item.why_it_matters ? `
      <div class="inspector-section">
        <span class="inspector-heading">Why it was kept</span>
        <p class="inspector-text">${escapeHtml(item.why_it_matters)}</p>
      </div>` : ''}

    <dl class="meta-grid">
      <div><dt>Source</dt><dd>${escapeHtml(sourceName(item.source))}</dd></div>
      <div><dt>Published</dt><dd>${item.published_at ? escapeHtml(new Date(item.published_at).toLocaleString()) : 'not recorded'}</dd></div>
      <div><dt>Category</dt><dd>${escapeHtml(categoryLabel(item.category))}</dd></div>
      ${item.priority_score ? `<div><dt>Priority score</dt><dd class="measured">${Number(item.priority_score).toFixed(1)}</dd></div>` : ''}
      <div class="wide"><dt>Link</dt><dd class="measured">${escapeHtml(item.url)}</dd></div>
    </dl>`;
}

/** A note belongs to a decision, so it appears once somebody has taken, finished or dismissed the item. */
function noteBox(item) {
  const t = triageOf(item);
  if (item.category === 'Skip' || t.status === 'open') return '';
  return `
    <div class="note-box">
      <label class="visually-hidden" for="triage-note">Note for the team</label>
      <textarea id="triage-note" class="field note-field" rows="2" maxlength="500" placeholder="Note for the team: ticket link, what you found, why not" data-url="${escapeHtml(item.url)}">${escapeHtml(t.note)}</textarea>
      <button type="button" class="btn" data-note-save data-url="${escapeHtml(item.url)}">Save note</button>
    </div>`;
}

function findItem(url) {
  return ((state.digest && state.digest.items) || []).find((i) => i.url === url);
}

// ─── Ratings ───────────────────────────────────────────────────────────────

function rateButtons(url) {
  const current = state.ratings[url] || 0;
  const u = escapeHtml(url);
  return `<span class="rate" role="group" aria-label="Rate this item">
    <button type="button" class="rate-btn" data-rate="1" data-url="${u}" aria-pressed="${current === 1}">Useful</button>
    <button type="button" class="rate-btn" data-rate="-1" data-url="${u}" aria-pressed="${current === -1}">Not useful</button>
  </span>`;
}

function paintRatings(url) {
  const current = state.ratings[url] || 0;
  document.querySelectorAll('.rate-btn').forEach((b) => {
    if (b.dataset.url === url) b.setAttribute('aria-pressed', String(Number(b.dataset.rate) === current));
  });
  renderFeedbackNote();
}

function renderFeedbackNote() {
  const values = Object.values(state.ratings);
  const up = values.filter((v) => v === 1).length;
  const down = values.filter((v) => v === -1).length;
  const note = document.getElementById('feedback-note');
  if (!note) return;
  note.textContent = values.length
    ? `Your ratings: ${up} useful, ${down} not useful. They steer the next harvest.`
    : 'Rate items as useful or not useful and the next harvest learns from them.';
}

async function submitRating(url, rating) {
  const previous = state.ratings[url] || 0;
  let key = storedHarvestKey();
  if (state.feedback.write_requires_key && !key) {
    key = await askHarvestKey();
    if (!key) return;
    storeHarvestKey(key);
  }
  state.ratings[url] = rating; // optimistic; rolled back below on failure
  paintRatings(url);
  try {
    const res = await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(key ? { 'X-API-Key': key } : {}) },
      body: JSON.stringify({ url, rating }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 401) storeHarvestKey('');
      throw new Error(data.error || data.detail || `Rating failed (${res.status})`);
    }
    if (rating === 0) delete state.ratings[url];
    showToast(data.persisted ? 'Saved.' : 'Saved on this server only. It resets if the server restarts.');
  } catch (err) {
    if (previous) state.ratings[url] = previous;
    else delete state.ratings[url];
    paintRatings(url);
    showToast(err.message || 'Could not save the rating.');
  }
  renderFeedbackNote();
}

document.addEventListener('click', async (e) => {
  const act = e.target.closest('[data-triage]');
  if (act) {
    e.stopPropagation();
    const item = findItem(act.dataset.url);
    if (!item) return;
    const ok = await setTriage(item, act.dataset.triage);
    if (ok && act.dataset.triage === 'doing') showToast('Yours now. Teammates see it in In progress.');
    return;
  }
  const save = e.target.closest('[data-note-save]');
  if (save) {
    const item = findItem(save.dataset.url);
    const box = document.getElementById('triage-note');
    if (item && box && await setTriage(item, triageOf(item).status, { note: box.value.trim() })) showToast('Note saved.');
    return;
  }
  const rate = e.target.closest('.rate-btn');
  if (rate) {
    e.stopPropagation();
    const next = Number(rate.dataset.rate);
    submitRating(rate.dataset.url, (state.ratings[rate.dataset.url] || 0) === next ? 0 : next);
    return;
  }
  const story = e.target.closest('.story-btn');
  if (story) {
    e.stopPropagation();
    openStory(story.dataset.story);
    return;
  }
  const btn = e.target.closest('[data-copy]');
  if (!btn) return;
  navigator.clipboard.writeText(btn.dataset.copy).then(
    () => showToast('Link copied.'),
    () => showToast('Could not copy the link.')
  );
});

let modalReturnFocus = null;

function openModal(item, returnTo, bodyHtml) {
  closeModal();
  modalReturnFocus = returnTo || null;
  const modal = document.createElement('div');
  modal.id = 'grid-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', item.title);
  if (item.url && !bodyHtml) modal.dataset.url = item.url;
  modal.innerHTML = `
    <div class="modal-panel">
      <button type="button" class="btn modal-close" id="modal-close" aria-label="Close">Close</button>
      ${bodyHtml || buildInspectorHtml(item)}
    </div>`;
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
  document.body.appendChild(modal);
  modal.querySelector('#modal-close').addEventListener('click', closeModal);
  modal.querySelector('#modal-close').focus();
}

/** After a status change the open reader (modal or split pane) must show the new status and note box. */
function refreshOpenPanel() {
  const item = state.filteredItems[state.selectedIndex];
  const modal = document.getElementById('grid-modal');
  const panel = modal ? modal.querySelector('.modal-panel') : null;
  if (!panel || !panel.querySelector('.team-section') || !modal.dataset.url) return;
  const current = findItem(modal.dataset.url) || item;
  const close = panel.querySelector('#modal-close');
  panel.innerHTML = '';
  panel.appendChild(close);
  panel.insertAdjacentHTML('beforeend', buildInspectorHtml(current));
}

function closeModal() {
  const modal = document.getElementById('grid-modal');
  if (!modal) return;
  modal.remove();
  if (modalReturnFocus && document.contains(modalReturnFocus)) modalReturnFocus.focus();
  modalReturnFocus = null;
}

// ─── Keyboard selection ────────────────────────────────────────────────────

function moveSelection(step) {
  const n = state.filteredItems.length;
  if (!n) return;
  state.selectedIndex = (state.selectedIndex + step + n) % n;
  const cards = document.querySelectorAll('.signal-card');
  cards.forEach((c, idx) => {
    const on = idx === state.selectedIndex;
    c.classList.toggle('is-selected', on);
    if (on) c.scrollIntoView({ block: 'nearest', behavior: 'auto' });
  });
  const insp = document.getElementById('sticky-inspector');
  if (insp) insp.innerHTML = buildInspectorHtml(state.filteredItems[state.selectedIndex]);
}
