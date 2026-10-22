/**
 * TechPulse "Signal Monolith" — Super Premium Client Controller
 * Reactive Technical Cockpit: Zero-Scroll Flight Mode, Dual Layouts,
 * Historical Date Switcher, Markdown Exporter, and Keyboard Flight Navigation.
 */

const state = {
  digest: null,
  availableDigests: [],
  selectedDate: 'latest',
  stats: null,
  viewMode: 'grid', // 'grid' | 'cockpit'
  activeCategory: 'curated', // 'curated' | 'Must Read' | 'Inspiration' | 'Skip' | 'all'
  activeSource: 'all',
  searchQuery: '',
  selectedIndex: 0,
  filteredItems: [],
  isHarvesting: false,
};

// Pure SVG Icons (Zero-Emoji Compliance)
const SOURCE_ICONS = {
  github_trending: `
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"></path>
    </svg>`,
  github_search: `
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>
    </svg>`,
  hacker_news: `
    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
      <path d="M0 0h24v24H0z" fill="none"/><path d="M2 2h20v20H2V2zm10 13.5l4-7.5h-2.5l-2.5 5-2.5-5H6l4 7.5v4.5h2v-4.5z"/>
    </svg>`,
  huggingface_papers: `
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
      <polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line>
      <line x1="16" y1="17" x2="8" y2="17"></line>
    </svg>`,
  devto_articles: `
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
      <polyline points="2 17 12 22 22 17"></polyline>
      <polyline points="2 12 12 17 22 12"></polyline>
    </svg>`,
  arxiv_ai: `
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line>
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
    </svg>`,
};

const SOURCE_NAMES = {
  github_trending: 'GitHub Trending',
  github_search: 'GitHub Search',
  hacker_news: 'Hacker News',
  huggingface_papers: 'Hugging Face',
  devto_articles: 'Dev.to',
  arxiv_ai: 'ArXiv AI',
};

// ─── Initialization ────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  setupHandlers();
  loadData();
});

function setupHandlers() {
  // Search with Ctrl+K shortcut
  const searchInput = document.getElementById('search-input');
  searchInput.addEventListener('input', (e) => {
    state.searchQuery = e.target.value.toLowerCase().trim();
    state.selectedIndex = 0;
    renderContent();
  });

  // Global Keyboard Shortcuts
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      searchInput.focus();
      return;
    }

    if (document.activeElement === searchInput) {
      if (e.key === 'Escape') searchInput.blur();
      return;
    }

    // Modal dismiss
    if (e.key === 'Escape') {
      const modal = document.getElementById('grid-modal');
      if (modal) modal.remove();
    }

    // Flight controls
    if (e.key === 'ArrowDown' || e.key === 'j') {
      e.preventDefault();
      selectNextItem();
    } else if (e.key === 'ArrowUp' || e.key === 'k') {
      e.preventDefault();
      selectPrevItem();
    } else if (e.key === 'Enter' || e.key === 'o') {
      const cur = state.filteredItems[state.selectedIndex];
      if (cur && cur.url) window.open(cur.url, '_blank');
    }
  });

  // Date Selector Dropdown
  const dateSelect = document.getElementById('date-select');
  dateSelect.addEventListener('change', async (e) => {
    state.selectedDate = e.target.value;
    if (state.selectedDate === 'latest') {
      await loadLatestDigest();
    } else {
      await loadDigestByDate(state.selectedDate);
    }
  });

  // Export Markdown Button
  document.getElementById('btn-export').addEventListener('click', handleExportMarkdown);

  // Category Segments
  document.querySelectorAll('.seg-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.seg-btn').forEach((b) => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      state.activeCategory = btn.dataset.category;
      state.selectedIndex = 0;
      renderContent();
    });
  });

  // Interactive KPI Cards Clicking
  document.getElementById('kpi-card-corpus').addEventListener('click', () => {
    switchCategoryTab('curated');
  });
  document.getElementById('kpi-card-must-read').addEventListener('click', () => {
    switchCategoryTab('Must Read');
  });
  document.getElementById('kpi-card-inspiration').addEventListener('click', () => {
    switchCategoryTab('Inspiration');
  });

  // View Switcher (Grid vs Cockpit Split)
  const gridBtn = document.getElementById('view-cards-btn');
  const cockpitBtn = document.getElementById('view-cockpit-btn');

  gridBtn.addEventListener('click', () => {
    gridBtn.classList.add('is-active');
    cockpitBtn.classList.remove('is-active');
    state.viewMode = 'grid';
    document.getElementById('keyboard-hint').style.display = 'none';
    renderContent();
  });

  cockpitBtn.addEventListener('click', () => {
    cockpitBtn.classList.add('is-active');
    gridBtn.classList.remove('is-active');
    state.viewMode = 'cockpit';
    document.getElementById('keyboard-hint').style.display = 'flex';
    renderContent();
  });

  // Harvest Trigger
  document.getElementById('btn-harvest').addEventListener('click', handleHarvestClick);
}

function switchCategoryTab(category) {
  document.querySelectorAll('.seg-btn').forEach((b) => {
    if (b.dataset.category === category) {
      b.classList.add('is-active');
    } else {
      b.classList.remove('is-active');
    }
  });
  state.activeCategory = category;
  state.selectedIndex = 0;
  renderContent();
}

// ─── Data Loading ──────────────────────────────────────────────────────────

async function loadData() {
  try {
    const [digestRes, statsRes, digestsListRes] = await Promise.all([
      fetch('/api/digest/latest'),
      fetch('/api/stats'),
      fetch('/api/digests'),
    ]);

    if (digestRes.ok) state.digest = await digestRes.json();
    if (statsRes.ok) state.stats = await statsRes.json();
    if (digestsListRes.ok) state.availableDigests = await digestsListRes.json();

    populateDateSelect();
    renderKPIs();
    renderCategoryBadges();
    renderSpectrumRail();
    renderContent();
  } catch (err) {
    console.error('Failed to load observatory data:', err);
    showToast('Failed to connect to API server.');
  }
}

async function loadLatestDigest() {
  try {
    const res = await fetch('/api/digest/latest');
    if (res.ok) {
      state.digest = await res.json();
      state.selectedIndex = 0;
      renderKPIs();
      renderCategoryBadges();
      renderSpectrumRail();
      renderContent();
      showToast(`Viewing latest digest (${state.digest.date})`);
    }
  } catch (err) {
    showToast('Failed to fetch latest digest.');
  }
}

async function loadDigestByDate(dateStr) {
  try {
    const res = await fetch(`/api/digest/${dateStr}`);
    if (res.ok) {
      state.digest = await res.json();
      state.selectedIndex = 0;
      renderKPIs();
      renderCategoryBadges();
      renderSpectrumRail();
      renderContent();
      showToast(`Loaded historical digest for ${dateStr}`);
    }
  } catch (err) {
    showToast(`Failed to fetch digest for ${dateStr}.`);
  }
}

function populateDateSelect() {
  const select = document.getElementById('date-select');
  select.innerHTML = '';

  const latestOpt = document.createElement('option');
  latestOpt.value = 'latest';
  latestOpt.textContent = 'Latest Digest';
  select.appendChild(latestOpt);

  if (Array.isArray(state.availableDigests)) {
    state.availableDigests.forEach((d) => {
      const opt = document.createElement('option');
      opt.value = d.date;
      opt.textContent = `${d.date} (${d.total_curated || 0} curated)`;
      if (state.digest && state.digest.date === d.date) {
        opt.selected = true;
      }
      select.appendChild(opt);
    });
  }
}

// ─── KPI Metric Rendering ──────────────────────────────────────────────────

function renderKPIs() {
  if (state.stats) {
    document.getElementById('kpi-tracked').textContent = state.stats.total_seen_urls || '0';
    if (state.stats.llm_model) {
      const modelShort = state.stats.llm_model.includes('/')
        ? state.stats.llm_model.split('/')[1]
        : state.stats.llm_model;
      document.getElementById('kpi-engine').textContent = modelShort;
    }
  }

  if (state.digest && state.digest.items) {
    const mustReads = state.digest.items.filter((i) => i.category === 'Must Read').length;
    const inspirations = state.digest.items.filter((i) => i.category === 'Inspiration').length;

    document.getElementById('kpi-must-read').textContent = mustReads;
    document.getElementById('kpi-inspiration').textContent = inspirations;
  }
}

// ─── Category Badges ───────────────────────────────────────────────────────

function renderCategoryBadges() {
  if (!state.digest || !state.digest.items) return;

  const items = state.digest.items;
  const curatedCount = items.filter((i) => i.category !== 'Skip').length;
  const mustReadCount = items.filter((i) => i.category === 'Must Read').length;
  const inspirationCount = items.filter((i) => i.category === 'Inspiration').length;
  const skipCount = items.filter((i) => i.category === 'Skip').length;

  document.getElementById('count-curated').textContent = curatedCount;
  document.getElementById('count-must-read').textContent = mustReadCount;
  document.getElementById('count-inspiration').textContent = inspirationCount;
  document.getElementById('count-skip').textContent = skipCount;
}

// ─── Spectrum Filter Rail ──────────────────────────────────────────────────

function renderSpectrumRail() {
  if (!state.digest || !state.digest.items) return;

  // Count items relevant to active category
  const relevantItems = state.digest.items.filter((i) => {
    if (state.activeCategory === 'curated') return i.category !== 'Skip';
    if (state.activeCategory !== 'all') return i.category === state.activeCategory;
    return true;
  });

  const counts = { all: relevantItems.length };
  relevantItems.forEach((item) => {
    counts[item.source] = (counts[item.source] || 0) + 1;
  });

  const rail = document.getElementById('spectrum-rail');
  rail.innerHTML = '';

  // All signals pill
  rail.appendChild(createSpectrumPill('all', 'All Sources', counts.all || 0));

  // Individual sources
  Object.keys(SOURCE_NAMES).forEach((key) => {
    if (counts[key]) {
      rail.appendChild(createSpectrumPill(key, SOURCE_NAMES[key], counts[key]));
    }
  });
}

function createSpectrumPill(key, label, count) {
  const pill = document.createElement('button');
  pill.className = `spectrum-pill ${state.activeSource === key ? 'is-active' : ''}`;
  const icon = SOURCE_ICONS[key] || '';
  pill.innerHTML = `${icon} <span>${label}</span> <span class="spectrum-count">${count}</span>`;

  pill.addEventListener('click', () => {
    document.querySelectorAll('.spectrum-pill').forEach((p) => p.classList.remove('is-active'));
    pill.classList.add('is-active');
    state.activeSource = key;
    state.selectedIndex = 0;
    renderContent();
  });
  return pill;
}

// ─── Content Filtering ─────────────────────────────────────────────────────

function computeFilteredItems() {
  if (!state.digest || !state.digest.items) return [];

  return state.digest.items.filter((item) => {
    // Category filter
    if (state.activeCategory === 'curated') {
      if (item.category === 'Skip') return false;
    } else if (state.activeCategory !== 'all') {
      if (item.category !== state.activeCategory) return false;
    }

    // Source filter
    if (state.activeSource !== 'all' && item.source !== state.activeSource) return false;

    // Search query
    if (state.searchQuery) {
      const text = `${item.title} ${item.summary} ${item.why_it_matters} ${item.source} ${item.category}`.toLowerCase();
      if (!text.includes(state.searchQuery)) return false;
    }
    return true;
  });
}

// ─── Master Content Rendering ──────────────────────────────────────────────

function renderContent() {
  const container = document.getElementById('content-container');
  state.filteredItems = computeFilteredItems();

  if (state.filteredItems.length === 0) {
    container.className = 'cards-grid-view';
    container.innerHTML = `
      <div style="grid-column: 1 / -1; background: var(--bg-card); border: 1px solid var(--border-hairline); border-radius: var(--radius-lg); padding: 48px 24px; text-align: center; box-shadow: var(--card-glass);">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="1.5" style="margin-bottom: 16px; opacity: 0.7;">
          <circle cx="12" cy="12" r="10"></circle>
          <path d="M12 8v4"></path>
          <path d="M12 16h.01"></path>
        </svg>
        <h3 style="font-size: 1.15rem; color: var(--text-title); margin-bottom: 8px;">No technical signals match the active filter</h3>
        <p style="font-size: 0.85rem; color: var(--text-body); max-width: 480px; margin: 0 auto 20px;">
          Try clearing your search query or switching to "High Signal" to see all curated repositories, research papers, and discussions.
        </p>
        <button class="btn-secondary" onclick="resetFilters()" style="margin: 0 auto;">
          <span>Reset Filters</span>
        </button>
      </div>
    `;
    return;
  }

  // Ensure selected index is in range
  if (state.selectedIndex >= state.filteredItems.length) {
    state.selectedIndex = 0;
  }

  if (state.viewMode === 'grid') {
    renderGridView(container);
  } else {
    renderCockpitSplitView(container);
  }
}

window.resetFilters = function () {
  document.getElementById('search-input').value = '';
  state.searchQuery = '';
  state.activeSource = 'all';
  switchCategoryTab('curated');
  renderSpectrumRail();
};

// ─── Layout Mode 1: Responsive Bento Cards Grid ────────────────────────────

function renderGridView(container) {
  container.className = 'cards-grid-view';
  container.innerHTML = '';

  state.filteredItems.forEach((item, index) => {
    const card = buildSignalCard(item, index, false);
    container.appendChild(card);
  });
}

// ─── Layout Mode 2: Viewport-Contained Cockpit Split (Zero Scroll) ─────────

function renderCockpitSplitView(container) {
  container.className = 'cockpit-split-view';
  container.innerHTML = '';

  // Left scrollable feed
  const feedPane = document.createElement('div');
  feedPane.className = 'scrollable-feed-pane';

  state.filteredItems.forEach((item, index) => {
    const card = buildSignalCard(item, index, true);
    feedPane.appendChild(card);
  });

  // Right sticky inspector pane
  const inspectorPane = document.createElement('div');
  inspectorPane.className = 'sticky-inspector-pane';
  inspectorPane.id = 'sticky-inspector';

  const selected = state.filteredItems[state.selectedIndex] || state.filteredItems[0];
  inspectorPane.innerHTML = buildInspectorHtml(selected);

  container.appendChild(feedPane);
  container.appendChild(inspectorPane);
}

// ─── Signal Card Builder ───────────────────────────────────────────────────

function buildSignalCard(item, index, isCompact) {
  const card = document.createElement('div');
  const isSelected = state.selectedIndex === index;
  const isSkip = item.category === 'Skip';
  const isMustRead = item.category === 'Must Read';

  card.className = `signal-card ${isSelected ? 'is-selected' : ''} ${isSkip ? 'is-skip' : ''}`;

  const iconSvg = SOURCE_ICONS[item.source] || '';
  const srcName = SOURCE_NAMES[item.source] || item.source;

  const badgeClass = isMustRead ? 'must-read' : (item.category === 'Inspiration' ? 'inspiration' : 'skip');

  card.innerHTML = `
    <div>
      <div class="card-topbar">
        <span class="badge-source">${iconSvg} ${srcName}</span>
        <span class="score-badge ${badgeClass}">
          ${item.category}
        </span>
      </div>

      <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" class="card-title" onclick="event.stopPropagation()">
        ${escapeHtml(item.title)}
      </a>

      <p class="card-desc">${escapeHtml(item.summary)}</p>

      ${item.why_it_matters && !isCompact ? `
        <div class="why-matters-pill">
          <strong style="color:var(--emerald);">Why it matters:</strong> ${escapeHtml(item.why_it_matters)}
        </div>
      ` : ''}
    </div>

    <div class="card-bottombar">
      <div class="tag-cluster">
        <span class="pill-tag">${srcName}</span>
        <span class="pill-tag">${item.category}</span>
      </div>

      <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" class="action-link" onclick="event.stopPropagation()">
        Open Signal
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
          <polyline points="15 3 21 3 21 9"></polyline>
          <line x1="10" y1="14" x2="21" y2="3"></line>
        </svg>
      </a>
    </div>
  `;

  card.addEventListener('click', () => {
    state.selectedIndex = index;
    if (state.viewMode === 'cockpit') {
      document.querySelectorAll('.signal-card').forEach((c) => c.classList.remove('is-selected'));
      card.classList.add('is-selected');
      const insp = document.getElementById('sticky-inspector');
      if (insp) insp.innerHTML = buildInspectorHtml(item);
    } else {
      openDrawerInspector(item);
    }
  });

  return card;
}

// ─── Inspector Pane HTML ───────────────────────────────────────────────────

function buildInspectorHtml(item) {
  if (!item) return '<div class="empty-canvas">Select a signal card to inspect its telemetry.</div>';

  const iconSvg = SOURCE_ICONS[item.source] || '';
  const srcName = SOURCE_NAMES[item.source] || item.source;
  const isMustRead = item.category === 'Must Read';
  const badgeClass = isMustRead ? 'must-read' : (item.category === 'Inspiration' ? 'inspiration' : 'skip');

  return `
    <div class="inspector-header">
      <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
        <span class="badge-source">${iconSvg} ${srcName}</span>
        <span class="score-badge ${badgeClass}">
          ${item.category}
        </span>
      </div>

      <h2 class="inspector-title">${escapeHtml(item.title)}</h2>

      <div style="display: flex; gap: 10px; align-items: center; margin-top: 14px;">
        <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" class="btn-primary" style="text-decoration:none;">
          Launch Source
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
            <polyline points="15 3 21 3 21 9"></polyline>
            <line x1="10" y1="14" x2="21" y2="3"></line>
          </svg>
        </a>
        <button class="btn-secondary" onclick="copyLink('${escapeHtml(item.url)}')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
          <span>Copy URL</span>
        </button>
      </div>
    </div>

    <div class="inspector-section">
      <span class="inspector-heading">Technical Brief</span>
      <p class="inspector-text">${escapeHtml(item.summary)}</p>
    </div>

    ${item.why_it_matters ? `
      <div class="inspector-section">
        <span class="inspector-heading" style="color:var(--emerald);">Strategic Relevance</span>
        <div class="why-matters-pill" style="margin:0; font-size:0.88rem;">
          ${escapeHtml(item.why_it_matters)}
        </div>
      </div>
    ` : ''}

    <div class="inspector-section">
      <span class="inspector-heading">Telemetry & Provenance</span>
      <div class="meta-grid">
        <div class="meta-item">
          <span class="label">Ingestion Source</span>
          <span class="val">${srcName}</span>
        </div>
        <div class="meta-item">
          <span class="label">Priority</span>
          <span class="val" style="color:${isMustRead ? 'var(--emerald)' : 'var(--amber)'};">${item.category}</span>
        </div>
        <div class="meta-item" style="grid-column: 1 / -1;">
          <span class="label">Direct URI</span>
          <span class="val" style="word-break:break-all; font-size:0.75rem; color:var(--text-body);">${escapeHtml(item.url)}</span>
        </div>
      </div>
    </div>
  `;
}

window.copyLink = function (url) {
  navigator.clipboard.writeText(url).then(() => {
    showToast('Direct URL copied to clipboard.');
  });
};

// ─── Modal / Drawer for Grid Mode ──────────────────────────────────────────

function openDrawerInspector(item) {
  let drawer = document.getElementById('grid-modal');
  if (!drawer) {
    drawer = document.createElement('div');
    drawer.id = 'grid-modal';
    drawer.style.cssText = `
      position: fixed; inset: 0; background: rgba(0,0,0,0.8); backdrop-filter: blur(8px);
      z-index: 100; display: flex; align-items: center; justify-content: center; padding: 24px;
    `;
    drawer.addEventListener('click', (e) => {
      if (e.target.id === 'grid-modal') drawer.remove();
    });
    document.body.appendChild(drawer);
  }

  drawer.innerHTML = `
    <div style="background:var(--bg-elevated); border:1px solid var(--border-hover); box-shadow:var(--card-glass); border-radius:var(--radius-lg); max-width:640px; width:100%; padding:28px; position:relative; max-height:85vh; overflow-y:auto;">
      <button onclick="document.getElementById('grid-modal').remove()" style="position:absolute; top:20px; right:20px; background:transparent; border:none; color:var(--text-muted); cursor:pointer;">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
      </button>
      ${buildInspectorHtml(item)}
    </div>
  `;
}

// ─── Keyboard Navigation ───────────────────────────────────────────────────

function selectNextItem() {
  if (state.filteredItems.length === 0) return;
  state.selectedIndex = (state.selectedIndex + 1) % state.filteredItems.length;
  updateSelection();
}

function selectPrevItem() {
  if (state.filteredItems.length === 0) return;
  state.selectedIndex = (state.selectedIndex - 1 + state.filteredItems.length) % state.filteredItems.length;
  updateSelection();
}

function updateSelection() {
  const cards = document.querySelectorAll('.signal-card');
  cards.forEach((c, idx) => {
    if (idx === state.selectedIndex) {
      c.classList.add('is-selected');
      c.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    } else {
      c.classList.remove('is-selected');
    }
  });

  const selected = state.filteredItems[state.selectedIndex];
  const insp = document.getElementById('sticky-inspector');
  if (insp && selected) insp.innerHTML = buildInspectorHtml(selected);
}

// ─── Export Markdown ───────────────────────────────────────────────────────

async function handleExportMarkdown() {
  const date = (state.digest && state.digest.date) ? state.digest.date : new Date().toISOString().split('T')[0];
  try {
    showToast(`Generating export for ${date}...`);
    const res = await fetch(`/api/digest/${date}/markdown`);
    if (!res.ok) throw new Error('Export endpoint returned error');
    const data = await res.json();

    const blob = new Blob([data.markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `TechPulse-Digest-${date}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast(`Downloaded TechPulse-Digest-${date}.md`);
  } catch (err) {
    console.error('Failed to export markdown:', err);
    showToast('Failed to export Markdown.');
  }
}

// ─── On-Demand Harvest Trigger ─────────────────────────────────────────────

async function handleHarvestClick() {
  if (state.isHarvesting) return;
  state.isHarvesting = true;

  const btn = document.getElementById('btn-harvest');
  btn.classList.add('is-loading');
  btn.querySelector('span').textContent = 'Harvesting...';

  showToast('Initiating multi-source parallel harvest cycle...');

  try {
    const res = await fetch('/api/harvest', { method: 'POST' });
    const data = await res.json();

    if (data.success) {
      state.digest = data.digest;
      await loadData();
      showToast(`Harvest complete in ${data.execution.duration_seconds}s! (${data.execution.must_reads} Must Read)`);
    } else {
      showToast('Harvest completed with no new updates.');
    }
  } catch (err) {
    console.error('Harvest trigger error:', err);
    showToast('Harvest failed. Check API server logs.');
  } finally {
    state.isHarvesting = false;
    btn.classList.remove('is-loading');
    btn.querySelector('span').textContent = 'Run Harvest';
  }
}

// ─── Toast System & Helpers ────────────────────────────────────────────────

function escapeHtml(str) {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function showToast(message) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--emerald)" stroke-width="2">
      <polyline points="20 6 9 17 4 12"></polyline>
    </svg>
    <span>${escapeHtml(message)}</span>
  `;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
