/**
 * TechPulse team triage, shared by the feed and the archive.
 * Who is handling which item. The server keeps it, so every teammate sees the same state.
 * Names are self-declared and stored in this browser only; there is no login.
 */

const NAME_KEY = 'techpulse.name';
const ACTION_STEPS = ['Patch', 'Try', 'Evaluate'];
const STEP_VERBS = { Patch: "I'll patch it", Try: "I'll try it", Evaluate: "I'll evaluate it", Read: "I'll read it", Watch: "I'll watch it" };

const triageState = { items: {}, writeRequiresKey: false, persistent: false };

function myName() {
  try {
    return localStorage.getItem(NAME_KEY) || '';
  } catch (err) {
    return '';
  }
}

function setMyName(name) {
  try {
    localStorage.setItem(NAME_KEY, name);
  } catch (err) {
    /* private mode: the name then lasts until the page closes */
  }
  triageState.sessionName = name;
  renderNameButton();
}

function currentName() {
  return myName() || triageState.sessionName || '';
}

function renderNameButton() {
  const label = document.getElementById('name-label');
  if (label) label.textContent = currentName() ? `You: ${currentName()}` : 'Set your name';
}

/** Ask for a display name in the native dialog. Resolves with the name, or '' if cancelled. */
function askName() {
  const dialog = document.getElementById('name-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return Promise.resolve('');
  const input = dialog.querySelector('input');
  input.value = currentName();
  return new Promise((resolve) => {
    dialog.addEventListener(
      'close',
      () => {
        const name = dialog.returnValue === 'ok' ? input.value.trim().replace(/\s+/g, ' ').slice(0, 40) : '';
        if (name) setMyName(name);
        resolve(name);
      },
      { once: true }
    );
    dialog.returnValue = '';
    dialog.showModal();
    input.focus();
    input.select();
  });
}

async function ensureName() {
  return currentName() || askName();
}

/** Load the team's triage state. Returns true when it differs from what was shown. */
async function loadTriage() {
  try {
    const data = await getJson('/api/triage', 15000);
    const changed = JSON.stringify(data.items) !== JSON.stringify(triageState.items);
    triageState.items = data.items || {};
    triageState.writeRequiresKey = !!data.write_requires_key;
    triageState.persistent = !!data.persistent;
    return changed;
  } catch (err) {
    return false; // the feed still works without it; every item then reads as open
  }
}

function triageOf(item) {
  return triageState.items[item.url] || { status: 'open', owner: '', note: '' };
}

function isActionable(item) {
  return item.category !== 'Skip' && ACTION_STEPS.includes(item.next_step);
}

/**
 * Take, finish, dismiss or reopen an item. Applies at once and rolls back if the server refuses.
 * `extra.note` changes only the note. Resolves true when saved.
 */
async function setTriage(item, status, extra = {}) {
  const previous = triageState.items[item.url];
  const noteOnly = extra.note !== undefined && previous && previous.status === status;

  let owner = noteOnly ? previous.owner : '';
  if (!noteOnly && status !== 'open') {
    owner = await ensureName();
    if (!owner) return false;
  }

  let key = storedHarvestKey();
  if (triageState.writeRequiresKey && !key) {
    key = await askHarvestKey();
    if (!key) return false;
    storeHarvestKey(key);
  }

  const note = status === 'open' ? '' : (extra.note !== undefined ? extra.note : (previous && previous.note) || '');
  if (status === 'open') delete triageState.items[item.url];
  else triageState.items[item.url] = { status, owner, note, updated_at: new Date().toISOString() };
  document.dispatchEvent(new CustomEvent('triage-changed'));

  try {
    const res = await fetch('/api/triage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(key ? { 'X-API-Key': key } : {}) },
      body: JSON.stringify({ url: item.url, status, owner, note }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 401) storeHarvestKey('');
      throw new Error(data.error || data.detail || `Could not save (${res.status})`);
    }
    if (data.persisted === false && !triageState.warned) {
      triageState.warned = true; // once per visit; the footer line keeps saying it
      showToast('Saved on this server only. It resets if the server restarts.');
    }
    return true;
  } catch (err) {
    if (previous) triageState.items[item.url] = previous;
    else delete triageState.items[item.url];
    document.dispatchEvent(new CustomEvent('triage-changed'));
    showToast(err.message || 'Could not save that.');
    return false;
  }
}

/** A short status label for an item, or '' while nobody has touched it. */
function triageChip(item) {
  const t = triageOf(item);
  const who = escapeHtml(t.owner || 'someone');
  if (t.status === 'doing') return `<span class="triage-chip is-doing">${who} is on it</span>`;
  if (t.status === 'done') return `<span class="triage-chip is-done">Done by ${who}</span>`;
  if (t.status === 'dismissed') return `<span class="triage-chip is-dismissed">Not for us, ${who}</span>`;
  return '';
}

/** The status chip, the actions that make sense for the current state, and the team's note. */
function triageControls(item) {
  if (item.category === 'Skip') return '';
  const t = triageOf(item);
  const url = escapeHtml(item.url);
  const btn = (act, label, cls = '') => `<button type="button" class="triage-btn ${cls}" data-triage="${act}" data-url="${url}">${label}</button>`;
  let actions;
  if (t.status === 'doing') actions = btn('done', 'Mark done', 'is-primary') + btn('open', 'Release');
  else if (t.status === 'open') actions = btn('doing', STEP_VERBS[item.next_step] || "I'll take it", 'is-primary') + btn('dismissed', 'Not for us');
  else actions = btn('open', 'Reopen');
  const note = t.note ? `<span class="triage-note">${escapeHtml(t.note)}</span>` : '';
  // A note belongs to a decision, so the button appears once somebody has taken, finished or dismissed the item.
  const noteBtn = t.status === 'open' ? '' : btn('', t.note ? 'Edit note' : 'Add note').replace('data-triage=""', 'data-note-edit');
  return `<div class="card-triage">${triageChip(item)}${actions}${noteBtn}${note}</div>`;
}
