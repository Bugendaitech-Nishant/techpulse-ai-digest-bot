/**
 * TechPulse digest archive.
 * Every figure comes from /api/insights (aggregated in SQLite) or /api/digest/latest.
 * Nothing here is estimated: delivery, reach and engagement are not tracked, so they are not shown.
 */

const regions = {
  readings: () => document.getElementById('readings'),
  history: () => document.getElementById('history-region'),
  runs: () => document.getElementById('runs-region'),
  sources: () => document.getElementById('sources-region'),
  top: () => document.getElementById('top-region'),
};

document.addEventListener('DOMContentLoaded', () => {
  initHarvest(load);
  load();
});

async function load() {
  const archive = document.getElementById('archive');
  const wake = document.getElementById('wake-note');
  const wakeTimer = setTimeout(() => { wake.hidden = false; }, 3000);
  archive.setAttribute('aria-busy', 'true');

  try {
    const [insights, latest] = await Promise.all([
      getJson('/api/insights'),
      getJson('/api/digest/latest').catch((err) => (String(err.message).includes('404') ? null : Promise.reject(err))),
      refreshQuota(),
    ]);
    render(insights, latest);
  } catch (err) {
    console.error('Failed to load the archive:', err);
    renderError();
  } finally {
    clearTimeout(wakeTimer);
    wake.hidden = true;
    archive.setAttribute('aria-busy', 'false');
  }
}

function pct(ratio) {
  return ratio === null || ratio === undefined ? '--' : `${Math.round(ratio * 100)}%`;
}

function render(insights, latest) {
  if (!insights.digests_total) {
    regions.readings().innerHTML = '';
    regions.sources().innerHTML = '';
    regions.top().innerHTML = '';
    regions.runs().innerHTML = '';
    regions.history().innerHTML = `
      <div class="state-panel">
        <h3>No digests yet</h3>
        <p>The archive fills as harvests run. Run the first one from the button above.</p>
      </div>`;
    document.getElementById('page-sub').textContent = 'Nothing has been harvested yet.';
    return;
  }

  document.getElementById('page-sub').textContent =
    `${insights.digests_total} ${insights.digests_total === 1 ? 'digest' : 'digests'} kept, last harvest ${relativeTime(insights.last_harvest_at) || 'time unknown'}.`;

  const backend = insights.latest ? `${insights.latest.ranking_backend} ${insights.latest.ranking_version}` : '--';
  const categories = insights.by_category || {};
  const fb = insights.feedback || {};
  regions.readings().innerHTML = `
    <div class="reading-cell">
      <span class="reading-label">Digests</span>
      <span class="reading-value">${insights.digests_total}</span>
      <span class="reading-note">one per day harvested</span>
    </div>
    <div class="reading-cell">
      <span class="reading-label">Items kept</span>
      <span class="reading-value">${insights.items_total}</span>
      <span class="reading-note">${categories['Must Read'] || 0} must read, ${categories.Inspiration || 0} inspiration</span>
    </div>
    <div class="reading-cell">
      <span class="reading-label">Keep rate</span>
      <span class="reading-value">${pct(insights.keep_rate)}</span>
      <span class="reading-note">of harvested items survive curation</span>
    </div>
    <div class="reading-cell">
      <span class="reading-label">Useful rate</span>
      <span class="reading-value">${pct(fb.useful_rate)}</span>
      <span class="reading-note">${ratingNote(fb)}</span>
    </div>
    <div class="reading-cell">
      <span class="reading-label">Ranked by</span>
      <span class="reading-value is-text">${escapeHtml(backend)}</span>
      <span class="reading-note">${insights.seen_in_window} URLs seen in ${insights.window_days} days</span>
    </div>`;

  renderHistory(insights.history);
  renderRuns(insights.runs || []);
  renderSources(insights.by_source, insights.items_total);
  renderTop(latest);
}

function ratingNote(fb) {
  const rated = (fb.up || 0) + (fb.down || 0);
  if (!rated) return 'rate items on the feed to start measuring';
  const top = fb.top10_useful_rate === null || fb.top10_useful_rate === undefined
    ? ''
    : `, ${pct(fb.top10_useful_rate)} within the top 10`;
  return `${fb.up} useful, ${fb.down} not useful${top}`;
}

function renderRuns(runs) {
  if (!runs.length) {
    regions.runs().innerHTML = '';
    return;
  }
  const rows = runs.map((r) => `
    <tr>
      <td>${escapeHtml(r.date)}</td>
      <td class="num">${Math.round(r.duration_seconds)} s</td>
      <td class="num">${r.harvested}</td>
      <td class="num">${r.kept}</td>
      <td class="num">${r.security}</td>
      <td>${r.failed_sources && r.failed_sources.length ? escapeHtml(r.failed_sources.map(sourceName).join(', ')) : 'none'}</td>
    </tr>`).join('');
  regions.runs().innerHTML = `
    <div class="table-wrap">
      <table class="data">
        <caption>Recent runs</caption>
        <thead><tr><th scope="col">Date</th><th scope="col" class="num">Duration</th><th scope="col" class="num">Harvested</th><th scope="col" class="num">Kept</th><th scope="col" class="num">Security</th><th scope="col">Failed sources</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function renderHistory(history) {
  const rows = history.map((h) => {
    const rate = h.harvested ? h.curated / h.harvested : null;
    return `
      <tr>
        <td><a href="/?date=${encodeURIComponent(h.date)}">${escapeHtml(h.date)}</a></td>
        <td class="num">${h.harvested}</td>
        <td class="num">${h.curated}</td>
        <td>
          <span class="bar-cell">
            <span class="measured">${pct(rate)}</span>
            <span class="bar" aria-hidden="true"><i style="width:${Math.round((rate || 0) * 100)}%"></i></span>
          </span>
        </td>
        <td><button type="button" class="btn" data-md="${escapeHtml(h.date)}">Markdown</button></td>
      </tr>`;
  }).join('');

  regions.history().innerHTML = `
    <div class="table-wrap">
      <table class="data">
        <caption>Harvested against kept</caption>
        <thead><tr><th scope="col">Date</th><th scope="col" class="num">Harvested</th><th scope="col" class="num">Kept</th><th scope="col">Keep rate</th><th scope="col">Export</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  regions.history().querySelectorAll('[data-md]').forEach((b) => b.addEventListener('click', () => downloadMarkdown(b.dataset.md)));
}

function renderSources(sources, total) {
  const measured = sources.some((s) => s.avg_priority !== null);
  const rows = sources.map((s) => {
    const share = total ? s.count / total : 0;
    return `
      <tr>
        <td><a href="/?src=${encodeURIComponent(s.source)}">${escapeHtml(sourceName(s.source))}</a></td>
        <td class="num">${s.count}</td>
        <td>
          <span class="bar-cell">
            <span class="measured">${pct(share)}</span>
            <span class="bar" aria-hidden="true"><i style="width:${Math.round(share * 100)}%"></i></span>
          </span>
        </td>
        ${measured ? `<td class="num">${s.avg_priority === null ? '--' : s.avg_priority}</td>` : ''}
      </tr>`;
  }).join('');

  regions.sources().innerHTML = `
    <div class="table-wrap">
      <table class="data">
        <caption>Where items came from</caption>
        <thead><tr><th scope="col">Source</th><th scope="col" class="num">Items</th><th scope="col">Share</th>${measured ? '<th scope="col" class="num">Avg priority</th>' : ''}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function renderTop(latest) {
  if (!latest || !latest.items || !latest.items.length) {
    regions.top().innerHTML = '';
    return;
  }
  const top = latest.items.slice(0, 5);
  regions.top().innerHTML = `
    <h2 class="section-title">Top of ${escapeHtml(latest.date)}</h2>
    <ol class="top-list">
      ${top.map((item, i) => `
        <li>
          <span class="card-rank">${String(i + 1).padStart(2, '0')}</span>
          <div>
            <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a>
            <p>${escapeHtml(sourceName(item.source))}</p>
          </div>
        </li>`).join('')}
    </ol>
    <p style="margin-top: var(--space-md);"><a href="/?date=${encodeURIComponent(latest.date)}">Open the full digest in the live feed</a></p>`;
}

function renderError() {
  regions.readings().innerHTML = '';
  regions.sources().innerHTML = '';
  regions.top().innerHTML = '';
  regions.runs().innerHTML = '';
  regions.history().innerHTML = `
    <div class="state-panel is-error">
      <h3>The archive did not load</h3>
      <p>The server did not answer in time. If it was idle, it needs about 30 seconds to wake. Nothing is lost.</p>
      <button type="button" class="btn btn-primary" id="btn-retry">Try again</button>
    </div>`;
  document.getElementById('btn-retry').addEventListener('click', load);
  document.getElementById('page-sub').textContent = 'The archive could not be reached.';
}
