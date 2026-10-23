/**
 * TechPulse shell: helpers shared by the live feed and the digest archive.
 * Escaping, toasts, the quota readout, the harvest action and Markdown export.
 */

const SOURCE_NAMES = {
  github_trending: 'GitHub Trending',
  github_search: 'GitHub Search',
  hacker_news: 'Hacker News',
  huggingface_papers: 'Hugging Face',
  devto_articles: 'Dev.to',
  arxiv_ai: 'ArXiv AI',
};

const HARVEST_KEY_STORAGE = 'techpulse.harvestKey';

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function sourceName(key) {
  return SOURCE_NAMES[key] || key;
}

function showToast(message) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 250);
  }, 4000);
}

/** Relative time from an ISO string, e.g. "3 h ago". Returns '' for unparseable input. */
function relativeTime(iso) {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return '';
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

/** Fetch JSON with a timeout; throws on HTTP errors so every region can show its error state. */
async function getJson(path, timeoutMs = 45000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(path, { signal: controller.signal });
    if (!res.ok) throw new Error(`${path} returned ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

// ─── Quota readout and harvest ─────────────────────────────────────────────

let latestQuota = null;

function renderQuota(quota) {
  latestQuota = quota;
  const dot = document.getElementById('quota-dot');
  const text = document.getElementById('quota-text');
  const btn = document.getElementById('btn-harvest');
  if (!dot || !text || !quota) return;

  dot.classList.remove('warning', 'danger');
  if (btn) {
    btn.classList.remove('is-cooldown');
    btn.title = 'Run a harvest now';
  }

  if (quota.is_harvesting) {
    dot.classList.add('warning');
    text.textContent = 'Harvest running';
  } else if (quota.cooldown_active) {
    dot.classList.add('warning');
    text.textContent = `Cooldown ${Math.ceil(quota.cooldown_remaining_seconds / 60)} min`;
    if (btn) {
      btn.classList.add('is-cooldown');
      btn.title = `Cooling down, ${quota.cooldown_remaining_seconds}s left`;
    }
  } else if (quota.hourly_harvests_remaining <= 0) {
    dot.classList.add('danger');
    text.textContent = `Cap reached 0/${quota.hourly_harvests_max}`;
    if (btn) {
      btn.classList.add('is-cooldown');
      btn.title = `Hourly cap of ${quota.hourly_harvests_max} reached`;
    }
  } else {
    text.textContent = `${quota.hourly_harvests_remaining}/${quota.hourly_harvests_max} left/hr`;
  }
}

function storedHarvestKey() {
  try {
    return sessionStorage.getItem(HARVEST_KEY_STORAGE) || '';
  } catch (err) {
    return '';
  }
}

function storeHarvestKey(key) {
  try {
    if (key) sessionStorage.setItem(HARVEST_KEY_STORAGE, key);
    else sessionStorage.removeItem(HARVEST_KEY_STORAGE);
  } catch (err) {
    /* sessionStorage can be blocked; the key then only lives for this request */
  }
}

/** Ask for the harvest API key in a native dialog. Resolves with the key, or '' if cancelled. */
function askHarvestKey() {
  const dialog = document.getElementById('key-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return Promise.resolve('');
  const input = dialog.querySelector('input');
  input.value = '';
  return new Promise((resolve) => {
    dialog.addEventListener(
      'close',
      () => resolve(dialog.returnValue === 'ok' ? input.value.trim() : ''),
      { once: true }
    );
    dialog.returnValue = '';
    dialog.showModal();
    input.focus();
  });
}

/**
 * Wire the header Run harvest button. `onDone` runs after a successful harvest
 * so the page can reload its data.
 */
function initHarvest(onDone) {
  const btn = document.getElementById('btn-harvest');
  if (!btn) return;
  let running = false;

  btn.addEventListener('click', async () => {
    if (running) return;

    let key = storedHarvestKey();
    if (latestQuota && latestQuota.auth_required && !key) {
      key = await askHarvestKey();
      if (!key) return;
      storeHarvestKey(key);
    }

    running = true;
    btn.classList.add('is-loading');
    btn.disabled = true;
    const label = btn.querySelector('span');
    const original = label.textContent;
    label.textContent = 'Harvesting';
    showToast('Harvest started. This can take a minute.');

    try {
      // Background mode: a full harvest takes minutes, longer than a hosted request may live.
      const res = await fetch('/api/harvest?background=true', {
        method: 'POST',
        headers: key ? { 'X-API-Key': key } : {},
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 202 && data.success) {
        const finished = await waitForHarvest();
        if (finished) {
          showToast('Harvest finished. Loading the new digest.');
          if (onDone) await onDone();
        } else {
          showToast('The harvest is still running. Reload in a few minutes.');
        }
      } else {
        if (res.status === 401) storeHarvestKey('');
        showToast(data.error || data.detail || 'The harvest was rejected.');
        if (data.quota) renderQuota(data.quota);
      }
    } catch (err) {
      console.error('Harvest request failed:', err);
      showToast('The harvest request failed. Check the connection and try again.');
    } finally {
      running = false;
      btn.classList.remove('is-loading');
      btn.disabled = false;
      label.textContent = original;
    }
  });
}

/** Poll the quota until the background harvest ends; true if it finished within `maxMs`. */
async function waitForHarvest(maxMs = 10 * 60 * 1000) {
  const started = Date.now();
  while (Date.now() - started < maxMs) {
    await new Promise((resolve) => setTimeout(resolve, 5000));
    try {
      // /api/health is uncached, unlike /api/stats, so is_harvesting is current.
      const health = await getJson('/api/health', 15000);
      if (health.quota) renderQuota(health.quota);
      if (health.quota && !health.quota.is_harvesting) return true;
    } catch (err) {
      /* a missed poll is fine; the next one retries */
    }
  }
  return false;
}

async function refreshQuota() {
  try {
    const stats = await getJson('/api/stats', 15000);
    if (stats.quota) renderQuota(stats.quota);
    return stats;
  } catch (err) {
    const text = document.getElementById('quota-text');
    if (text) text.textContent = 'Quota unavailable';
    return null;
  }
}

// ─── Markdown export ───────────────────────────────────────────────────────

async function downloadMarkdown(date) {
  try {
    showToast(`Preparing ${date}.`);
    const data = await getJson(`/api/digest/${encodeURIComponent(date)}/markdown`, 20000);
    const blob = new Blob([data.markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `TechPulse-Digest-${date}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast(`Saved TechPulse-Digest-${date}.md`);
  } catch (err) {
    console.error('Markdown export failed:', err);
    showToast('The Markdown export failed.');
  }
}
