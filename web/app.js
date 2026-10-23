/**
 * TechPulse live feed controller.
 * Ranked list and split view, filters kept in the URL, four data states
 * (loading, empty, error, full) and readings drawn from /api/insights.
 * Shared helpers (escapeHtml, toasts, quota, harvest, export) live in shell.js.
 */

const CATEGORY_LABELS = { curated: 'High signal', 'Must Read': 'Must read', Inspiration: 'Inspiration', Skip: 'Filtered out' };
const VALID_CATEGORIES = Object.keys(CATEGORY_LABELS);

const state = {
  digest: null,
  availableDigests: [],
  selectedDate: 'latest',
  stats: null,
  insights: null,
  viewMode: 'grid', // 'grid' (ranked list) | 'cockpit' (split view)
  activeCategory: 'curated',
  activeSource: 'all',
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
  state.searchQuery = (p.get('q') || '').toLowerCase().trim();
  state.selectedDate = p.get('date') || 'latest';
  state.viewMode = p.get('view') === 'split' ? 'cockpit' : 'grid';
}

function writeUrlState() {
  const p = new URLSearchParams();
  if (state.activeCategory !== 'curated') p.set('cat', state.activeCategory);
  if (state.activeSource !== 'all') p.set('src', state.activeSource);
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
});

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

  document.getElementById('kpi-card-corpus').addEventListener('click', () => switchCategoryTab('curated'));
  document.getElementById('kpi-card-must-read').addEventListener('click', () => switchCategoryTab('Must Read'));
  document.getElementById('kpi-card-inspiration').addEventListener('click', () => switchCategoryTab('Inspiration'));

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
  renderContent();
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
    const [stats, digests, insights] = await Promise.all([
      refreshQuota(),
      getJson('/api/digests').catch(() => []),
      getJson('/api/insights').catch(() => null),
    ]);
    state.stats = stats;
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
  renderReadings();
  renderCategoryBadges();
  renderSpectrumRail();
  renderContent();
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
  const mustReads = items.filter((i) => i.category === 'Must Read').length;
  const inspirations = items.filter((i) => i.category === 'Inspiration').length;
  const curated = items.filter((i) => i.category !== 'Skip').length;

  const seen = state.insights ? state.insights.seen_in_window : (state.stats && state.stats.total_seen_urls);
  document.getElementById('kpi-tracked').textContent = Number.isFinite(seen) ? seen : '--';
  document.getElementById('kpi-must-read').textContent = state.digest ? mustReads : '--';
  document.getElementById('kpi-inspiration').textContent = state.digest ? inspirations : '--';
  document.getElementById('kpi-must-note').textContent = curated ? `of ${curated} curated` : 'of the curated set';

  const model = state.stats && state.stats.llm_model;
  document.getElementById('kpi-engine').textContent = model ? (model.includes('/') ? model.split('/')[1] : model) : '--';
  const backend = state.digest && state.digest.ranking_backend;
  const version = state.digest && state.digest.ranking_version;
  document.getElementById('kpi-latency').textContent = backend ? `ranked by ${backend} ${version || ''}`.trim() : 'ranking backend';

  const sub = document.getElementById('page-sub');
  if (state.digest) {
    const kept = state.digest.total_harvested ? ` from ${state.digest.total_harvested} harvested` : '';
    const when = state.digest.created_at ? `, built ${relativeTime(state.digest.created_at)}` : '';
    sub.textContent = `${state.digest.date}: ${curated} curated${kept}${when}.`;
  } else {
    sub.textContent = 'No digest to show.';
  }
}

function renderCategoryBadges() {
  const items = (state.digest && state.digest.items) || [];
  document.getElementById('count-curated').textContent = items.filter((i) => i.category !== 'Skip').length;
  document.getElementById('count-must-read').textContent = items.filter((i) => i.category === 'Must Read').length;
  document.getElementById('count-inspiration').textContent = items.filter((i) => i.category === 'Inspiration').length;
  document.getElementById('count-skip').textContent = items.filter((i) => i.category === 'Skip').length;
}

// ─── Source filter rail ────────────────────────────────────────────────────

function renderSpectrumRail() {
  const rail = document.getElementById('spectrum-rail');
  rail.innerHTML = '';
  if (!state.digest || !state.digest.items) return;

  const relevant = state.digest.items.filter((i) => {
    if (state.activeCategory === 'curated') return i.category !== 'Skip';
    return i.category === state.activeCategory;
  });
  const counts = {};
  relevant.forEach((item) => { counts[item.source] = (counts[item.source] || 0) + 1; });

  rail.appendChild(createSpectrumPill('all', 'All sources', relevant.length));
  Object.keys(counts)
    .sort((a, b) => counts[b] - counts[a])
    .forEach((key) => rail.appendChild(createSpectrumPill(key, sourceName(key), counts[key])));
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
    renderContent();
  });
  return pill;
}

// ─── Filtering and rendering ───────────────────────────────────────────────

function computeFilteredItems() {
  if (!state.digest || !state.digest.items) return [];
  return state.digest.items.filter((item) => {
    if (state.activeCategory === 'curated') {
      if (item.category === 'Skip') return false;
    } else if (item.category !== state.activeCategory) {
      return false;
    }
    if (state.activeSource !== 'all' && item.source !== state.activeSource) return false;
    if (state.searchQuery) {
      const text = `${item.title} ${item.summary} ${item.why_it_matters} ${item.source} ${item.category}`.toLowerCase();
      if (!text.includes(state.searchQuery)) return false;
    }
    return true;
  });
}

function renderContent() {
  const container = document.getElementById('content-container');
  if (!state.digest) return;
  state.filteredItems = computeFilteredItems();

  if (state.filteredItems.length === 0) {
    renderEmpty(container, 'Nothing matches these filters', 'Clear the search or switch back to High signal.', true);
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
      ${withReset ? '<button type="button" class="btn" id="btn-reset">Reset filters</button>' : ''}
    </div>`;
  const reset = document.getElementById('btn-reset');
  if (reset) reset.addEventListener('click', resetFilters);
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
  state.activeCategory = 'curated';
  state.selectedIndex = 0;
  syncControls();
  writeUrlState();
  renderSpectrumRail();
  renderContent();
}

function renderListView(container) {
  container.className = 'cards-grid-view';
  container.innerHTML = '';
  state.filteredItems.forEach((item, index) => container.appendChild(buildSignalCard(item, index)));
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

function buildSignalCard(item, index) {
  const card = document.createElement('div');
  card.setAttribute('role', 'listitem');
  card.className = `signal-card ${state.selectedIndex === index ? 'is-selected' : ''} ${item.category === 'Skip' ? 'is-skip' : ''}`;
  card.tabIndex = 0;

  card.innerHTML = `
    <span class="card-rank">${String(index + 1).padStart(2, '0')}</span>
    <div class="card-main">
      <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" class="card-title">${escapeHtml(item.title)}</a>
      <p class="card-desc">${escapeHtml(item.summary)}</p>
    </div>
    <div class="card-foot">
      <span class="badge-source">${escapeHtml(sourceName(item.source))}</span>
      <span class="score-badge ${badgeClass(item.category)}">${escapeHtml(categoryLabel(item.category))}</span>
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
  card.addEventListener('click', activate);
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
    </div>

    <div class="inspector-section">
      <span class="inspector-heading">Summary</span>
      <p class="inspector-text">${escapeHtml(item.summary)}</p>
    </div>

    ${item.why_it_matters ? `
      <div class="inspector-section">
        <span class="inspector-heading">Why it was kept</span>
        <p class="inspector-text">${escapeHtml(item.why_it_matters)}</p>
      </div>` : ''}

    <dl class="meta-grid">
      <div><dt>Source</dt><dd>${escapeHtml(sourceName(item.source))}</dd></div>
      <div><dt>Category</dt><dd>${escapeHtml(categoryLabel(item.category))}</dd></div>
      ${item.priority_score ? `<div><dt>Priority score</dt><dd class="measured">${Number(item.priority_score).toFixed(1)}</dd></div>` : ''}
      <div class="wide"><dt>Link</dt><dd class="measured">${escapeHtml(item.url)}</dd></div>
    </dl>`;
}

document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-copy]');
  if (!btn) return;
  navigator.clipboard.writeText(btn.dataset.copy).then(
    () => showToast('Link copied.'),
    () => showToast('Could not copy the link.')
  );
});

let modalReturnFocus = null;

function openModal(item, returnTo) {
  closeModal();
  modalReturnFocus = returnTo || null;
  const modal = document.createElement('div');
  modal.id = 'grid-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', item.title);
  modal.innerHTML = `
    <div class="modal-panel">
      <button type="button" class="btn modal-close" id="modal-close" aria-label="Close">Close</button>
      ${buildInspectorHtml(item)}
    </div>`;
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
  document.body.appendChild(modal);
  modal.querySelector('#modal-close').addEventListener('click', closeModal);
  modal.querySelector('#modal-close').focus();
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
