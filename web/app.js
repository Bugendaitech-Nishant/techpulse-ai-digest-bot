/**
 * TechPulse briefing.
 * One day, sorted by the server (/api/briefing) into what touches the team's stack, the best few
 * reads, and everything else. Triage and names live in triage.js; shared helpers in shell.js.
 */

const state = {
  briefing: null,
  days: [], // digest dates, newest first
  date: 'latest',
  ratings: {}, // url -> 1 useful, -1 not useful
  feedback: { persistent: false, write_requires_key: false },
  stats: null,
};

const SECTIONS = [
  { tier: 'alert', title: 'Act on', note: 'Touches what you run and asks for something.' },
  { tier: 'stack', title: 'Touches your stack', note: 'Good to know. Nothing to do yet.' },
  { tier: 'pick', title: 'Worth your time', note: 'Not about your stack, but the best of the day.' },
];

// ─── Start ─────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  state.date = new URLSearchParams(window.location.search).get('date') || 'latest';
  renderNameButton();
  setupHandlers();
  initHarvest(loadAll);
  loadAll();
  setInterval(refreshTriage, 60000); // teammates act while this page is open
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshTriage(); });
});

function setupHandlers() {
  document.getElementById('btn-brief').addEventListener('click', copyBrief);
  document.getElementById('btn-name').addEventListener('click', async () => { if (await askName()) render(); });
  document.getElementById('btn-export').addEventListener('click', () => {
    if (state.briefing) downloadMarkdown(state.briefing.date);
  });
  document.getElementById('day-prev').addEventListener('click', () => stepDay(1));
  document.getElementById('day-next').addEventListener('click', () => stepDay(-1));
  document.addEventListener('triage-changed', render);
  document.addEventListener('click', onClick);
  document.addEventListener('submit', onSubmit);
}

async function refreshTriage() {
  const editing = document.activeElement && ['TEXTAREA', 'INPUT'].includes(document.activeElement.tagName);
  if (document.hidden || editing) return;
  if (await loadTriage()) render();
}

// ─── Data ──────────────────────────────────────────────────────────────────

function setBusy(busy) {
  document.getElementById('briefing').setAttribute('aria-busy', busy ? 'true' : 'false');
}

async function loadAll() {
  const wake = document.getElementById('wake-note');
  const wakeTimer = setTimeout(() => { wake.hidden = false; }, 3000);
  setBusy(true);
  try {
    const [stats, days, feedback] = await Promise.all([
      refreshQuota(),
      getJson('/api/digests').catch(() => []),
      getJson('/api/feedback').catch(() => null),
      loadTriage(),
    ]);
    state.stats = stats;
    state.days = Array.isArray(days) ? days.map((d) => d.date) : [];
    if (feedback) { state.ratings = feedback.ratings || {}; state.feedback = feedback; }
    await loadDay();
  } catch (err) {
    console.error('Failed to load the briefing:', err);
    renderError(() => loadAll());
  } finally {
    clearTimeout(wakeTimer);
    wake.hidden = true;
    setBusy(false);
  }
}

async function loadDay() {
  try {
    state.briefing = await getJson(`/api/briefing?date=${encodeURIComponent(state.date)}`);
  } catch (err) {
    state.briefing = null;
    if (String(err.message).includes('404')) renderNone();
    else renderError(() => loadDay());
    return;
  }
  render();
}

function stepDay(direction) {
  if (!state.briefing) return;
  const next = state.days[state.days.indexOf(state.briefing.date) + direction];
  if (!next) return;
  state.date = next === state.days[0] ? 'latest' : next;
  history.replaceState(null, '', state.date === 'latest' ? window.location.pathname : `?date=${next}`);
  loadDay();
}

// ─── Render ────────────────────────────────────────────────────────────────

function itemsOf(tier) {
  return ((state.briefing && state.briefing.items) || []).filter((i) => i.tier === tier);
}

function render() {
  const b = state.briefing;
  if (!b) return;
  renderDayNav();
  renderLede();
  renderStack();

  const focus = document.activeElement && document.activeElement.closest && document.activeElement.closest('.note-form');
  if (focus) return; // do not rebuild the page under someone who is typing a note

  const content = document.getElementById('content');
  const parts = SECTIONS.map((s) => renderSection(s, itemsOf(s.tier))).join('');
  const quiet = !itemsOf('alert').length && !itemsOf('stack').length
    ? '<p class="quiet">Nothing here touches the tools you run. That is a result, not a gap: you can stop at the reading list.</p>'
    : '';
  content.innerHTML = quiet + parts + renderRest('more', 'Also kept', itemsOf('more')) + renderRest('filtered', 'Filtered out, with the reason', itemsOf('filtered'));
  renderColophon();
}

function renderDayNav() {
  const b = state.briefing;
  const i = state.days.indexOf(b.date);
  document.getElementById('day-prev').disabled = i === -1 || i >= state.days.length - 1;
  document.getElementById('day-next').disabled = i <= 0;
  const when = new Date(`${b.date}T12:00:00`);
  const label = Number.isNaN(when.getTime()) ? b.date : when.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
  document.getElementById('day-label').textContent = i === 0 || state.date === 'latest' ? `${label}, latest` : label;
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function renderLede() {
  const b = state.briefing;
  const c = b.counts;
  let headline;
  if (c.alerts) headline = `${plural(c.alerts, 'thing needs', 'things need')} your attention.`;
  else if (c.stack) headline = `Nothing to patch. ${plural(c.stack, 'item touches', 'items touch')} your stack.`;
  else headline = 'Quiet day for your stack.';
  document.getElementById('headline').textContent = headline;

  const when = b.created_at ? ` Built ${relativeTime(b.created_at)}.` : '';
  const from = b.total_harvested ? ` of ${b.total_harvested} harvested` : '';
  document.getElementById('lede-sub').textContent =
    `${c.picks} worth your time, ${c.more} more kept, ${c.filtered} filtered out${from}.${when}`;
}

function renderStack() {
  const strip = document.getElementById('stack-strip');
  const stack = state.briefing.stack || [];
  if (!stack.length) {
    strip.innerHTML = '<p class="muted">No stack defined, so nothing can be matched. Set <code>tools</code> in config/profile.toml.</p>';
    return;
  }
  strip.innerHTML = '<span class="rail-label">Your stack</span>' + stack.map((s) => {
    const cls = s.hits && !s.broad ? 'is-hit' : '';
    const title = s.broad ? 'Too common to count on its own' : s.hits ? `${plural(s.hits, 'item mentions', 'items mention')} ${s.name} today` : `Nothing about ${s.name} today`;
    return `<span class="stack-chip ${cls}" title="${escapeHtml(title)}">${escapeHtml(s.name)}${s.hits ? `<b>${s.hits}</b>` : ''}</span>`;
  }).join('');
}

function renderSection(section, items) {
  if (!items.length) return '';
  return `
    <section class="tier tier-${section.tier}" aria-labelledby="h-${section.tier}">
      <header class="tier-head">
        <h2 id="h-${section.tier}">${section.title} <span class="tier-count">${items.length}</span></h2>
        <p>${section.note}</p>
      </header>
      ${items.map(card).join('')}
    </section>`;
}

function renderRest(id, title, items) {
  if (!items.length) return '';
  const rows = items.map((i) => `
    <li>
      <a href="${escapeHtml(i.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(i.title)}</a>
      <span class="muted">${escapeHtml(sourceName(i.source))}</span>
      <p>${escapeHtml(plainText(i.category === 'Skip' ? i.why_it_matters : i.summary))}</p>
    </li>`).join('');
  return `
    <details class="rest" id="rest-${id}">
      <summary>${title} <span class="tier-count">${items.length}</span></summary>
      <ul class="rest-list">${rows}</ul>
    </details>`;
}

function ageLabel(item) {
  return (item.published_at && relativeTime(item.published_at)) || '';
}

function checkLine(item) {
  if (item.verification === 'unverified') return `<span class="check check-warn" title="${escapeHtml(item.verification_note)}">Not fully backed by its source</span>`;
  if (item.verification === 'verified' || item.verification === 'corrected') return '<span class="check">Checked against source</span>';
  return '';
}

function card(item) {
  const meta = [sourceName(item.source), ageLabel(item)].filter(Boolean).map(escapeHtml).join(' · ');
  const touches = item.stack_hits && item.stack_hits.length
    ? `<p class="touches">Touches ${item.stack_hits.map((h) => `<b>${escapeHtml(h)}</b>`).join(', ')}</p>` : '';
  const action = item.action
    ? `<p class="action"><strong>${escapeHtml(item.next_step)}</strong> ${escapeHtml(item.action)}</p>` : '';
  const story = item.story_id ? `<button type="button" class="story-btn" data-story="${escapeHtml(item.story_id)}">Follow the story</button>` : '';
  const handled = ['done', 'dismissed'].includes(triageOf(item).status);
  return `
    <article class="brief-card ${handled ? 'is-handled' : ''}">
      <p class="kicker">${meta}</p>
      <h3><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a></h3>
      ${touches}
      <p class="summary">${escapeHtml(plainText(item.summary))}</p>
      ${action}
      <div class="brief-foot">
        ${item.actionable ? triageControls(item) : ''}
        ${rateButtons(item.url)}
        ${story}
        ${checkLine(item)}
      </div>
    </article>`;
}

function renderColophon() {
  const parts = [];
  const model = state.stats && state.stats.llm_model;
  if (model) parts.push(`Curated by ${model.includes('/') ? model.split('/')[1] : model}`);
  parts.push(triageState.persistent ? 'team status is saved to GitHub' : 'team status resets if the server restarts');
  parts.push('stack is set in config/profile.toml');
  document.getElementById('colophon').textContent = parts.join(' · ');
}

function renderNone() {
  document.getElementById('headline').textContent = 'No briefing yet.';
  document.getElementById('lede-sub').textContent = 'Run a harvest from the Admin menu to build the first one.';
  document.getElementById('content').innerHTML = '';
  document.getElementById('stack-strip').innerHTML = '';
  document.getElementById('day-label').textContent = 'No digest';
}

function renderError(retry) {
  document.getElementById('content').innerHTML = `
    <div class="state-panel is-error">
      <h3>The briefing did not load</h3>
      <p>The server did not answer in time. If it was idle, it needs about 30 seconds to wake. Nothing is lost.</p>
      <button type="button" class="btn btn-primary" id="btn-retry">Try again</button>
    </div>`;
  document.getElementById('btn-retry').addEventListener('click', retry);
}

// ─── Actions ───────────────────────────────────────────────────────────────

function findItem(url) {
  return ((state.briefing && state.briefing.items) || []).find((i) => i.url === url);
}

async function onClick(e) {
  const act = e.target.closest('[data-triage]');
  if (act) {
    const item = findItem(act.dataset.url);
    if (item && (await setTriage(item, act.dataset.triage)) && act.dataset.triage === 'doing') showToast('Yours now. Your team sees it in the brief.');
    return;
  }
  const edit = e.target.closest('[data-note-edit]');
  if (edit) {
    const item = findItem(edit.dataset.url);
    const slot = edit.closest('.card-triage');
    if (!item || !slot) return;
    slot.insertAdjacentHTML('afterend', `
      <form class="note-form" data-url="${escapeHtml(item.url)}">
        <label class="visually-hidden" for="note-input">Note for the team</label>
        <input id="note-input" class="field" maxlength="500" value="${escapeHtml(triageOf(item).note)}" placeholder="Ticket link, what you found, why not">
        <button type="submit" class="btn">Save</button>
      </form>`);
    edit.hidden = true;
    slot.parentElement.querySelector('.note-form input').focus();
    return;
  }
  const rate = e.target.closest('.rate-btn');
  if (rate) {
    const next = Number(rate.dataset.rate);
    submitRating(rate.dataset.url, (state.ratings[rate.dataset.url] || 0) === next ? 0 : next);
    return;
  }
  const story = e.target.closest('.story-btn');
  if (story) { openStory(story.dataset.story); return; }
  const menu = document.getElementById('admin-menu');
  if (menu && menu.open && !menu.contains(e.target)) menu.open = false;
}

async function onSubmit(e) {
  const form = e.target.closest('.note-form');
  if (!form) return;
  e.preventDefault();
  const item = findItem(form.dataset.url);
  if (!item) return;
  const note = form.querySelector('input').value.trim();
  form.remove();
  if (await setTriage(item, triageOf(item).status, { note })) showToast('Note saved.');
  render();
}

async function copyBrief() {
  if (!state.briefing) { showToast('There is no briefing to copy yet.'); return; }
  let markdown;
  try {
    markdown = (await getJson(`/api/brief?date=${encodeURIComponent(state.briefing.date)}`, 20000)).markdown;
  } catch (err) {
    showToast('Could not build the brief.');
    return;
  }
  try {
    await navigator.clipboard.writeText(markdown);
    showToast('Brief copied. Paste it into chat or your standup notes.');
  } catch (err) {
    showToast('Your browser blocked copying. Open the Markdown export under Admin instead.');
  }
}

async function openStory(storyId) {
  let items;
  try {
    items = (await getJson(`/api/story/${encodeURIComponent(storyId)}`)).items;
  } catch (err) {
    showToast('Could not load the story.');
    return;
  }
  document.getElementById('story-list').innerHTML = items.map((i) => `
    <li>
      <span class="measured">${escapeHtml((i.published_at || i.digest_date || '').slice(0, 10))}</span>
      <a href="${escapeHtml(i.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(i.title)}</a>
      <p>${escapeHtml(plainText(i.next_step_detail || i.summary))}</p>
    </li>`).join('');
  document.getElementById('story-dialog').showModal();
}

// ─── Ratings: they teach tomorrow's curator ────────────────────────────────

function rateButtons(url) {
  const current = state.ratings[url] || 0;
  const u = escapeHtml(url);
  return `<span class="rate" role="group" aria-label="Was this useful?">
    <button type="button" class="rate-btn" data-rate="1" data-url="${u}" aria-pressed="${current === 1}">Useful</button>
    <button type="button" class="rate-btn" data-rate="-1" data-url="${u}" aria-pressed="${current === -1}">Not useful</button>
  </span>`;
}

function paintRatings(url) {
  const current = state.ratings[url] || 0;
  document.querySelectorAll('.rate-btn').forEach((b) => {
    if (b.dataset.url === url) b.setAttribute('aria-pressed', String(Number(b.dataset.rate) === current));
  });
}

async function submitRating(url, rating) {
  const previous = state.ratings[url] || 0;
  let key = storedHarvestKey();
  if (state.feedback.write_requires_key && !key) {
    key = await askHarvestKey();
    if (!key) return;
    storeHarvestKey(key);
  }
  if (rating) state.ratings[url] = rating; else delete state.ratings[url]; // optimistic; rolled back below on failure
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
    showToast(data.persisted ? 'Saved. It steers the next harvest.' : 'Saved on this server only. It resets if the server restarts.');
  } catch (err) {
    if (previous) state.ratings[url] = previous; else delete state.ratings[url];
    paintRatings(url);
    showToast(err.message || 'Could not save the rating.');
  }
}
