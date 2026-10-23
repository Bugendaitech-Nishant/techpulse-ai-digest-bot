const state = { items: [], index: 0, selected: null };
const $ = (id) => document.getElementById(id);

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = false;
}

function updateProgress() {
  const labelled = state.items.filter((item) => item.label_source === "human").length;
  const percent = state.items.length ? Math.round((labelled / state.items.length) * 100) : 0;
  $("progress-count").textContent = `${labelled} / ${state.items.length} labelled`;
  $("progress-percent").textContent = `${percent}%`;
  $("progress-bar").style.width = `${percent}%`;
}

function render() {
  updateProgress();
  const item = state.items[state.index];
  if (!item) {
    $("review-card").hidden = true;
    $("complete").hidden = false;
    return;
  }
  $("complete").hidden = true;
  $("review-card").hidden = false;
  $("item-number").textContent = `${state.index + 1} / ${state.items.length}`;
  $("item-source").textContent = item.source;
  $("item-title").textContent = item.title;
  $("item-url").textContent = item.url;
  $("item-url").href = item.url;
  $("item-description").textContent = item.description || "No description available.";
  $("item-why").textContent = item.why_it_matters || "No additional context available.";
  $("notes").value = item.label_source === "human" ? (item.label_notes || "") : "";
  state.selected = item.label_source === "human" ? item.relevance : null;
  document.querySelectorAll("[data-score]").forEach((button) => {
    button.classList.toggle("selected", Number(button.dataset.score) === state.selected);
  });
  $("save").disabled = state.selected === null;
}

async function saveLabel() {
  $("save").disabled = true;
  try {
    const response = await fetch(`/api/label-review/${state.index}`, {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({relevance: state.selected, label_notes: $("notes").value}),
    });
    if (!response.ok) throw new Error((await response.json()).detail || "Could not save label.");
    state.items[state.index] = (await response.json()).item;
    state.index += 1;
    render();
  } catch (error) {
    showError(error.message);
    $("save").disabled = state.selected === null;
  }
}

async function load() {
  try {
    const response = await fetch("/api/label-review");
    if (!response.ok) throw new Error("Could not load the review fixture.");
    state.items = (await response.json()).items;
    const firstUnlabelled = state.items.findIndex((item) => item.label_source !== "human");
    state.index = firstUnlabelled === -1 ? state.items.length : firstUnlabelled;
    render();
  } catch (error) {
    showError(error.message);
  }
}

document.querySelectorAll("[data-score]").forEach((button) => {
  button.addEventListener("click", () => {
    state.selected = Number(button.dataset.score);
    document.querySelectorAll("[data-score]").forEach((candidate) => candidate.classList.remove("selected"));
    button.classList.add("selected");
    $("save").disabled = false;
  });
});
$("save").addEventListener("click", saveLabel);
$("skip").addEventListener("click", () => { state.index += 1; render(); });
document.addEventListener("keydown", (event) => {
  if (event.key >= "0" && event.key <= "4") document.querySelector(`[data-score="${event.key}"]`).click();
  if (event.key === "Enter" && !event.shiftKey && state.selected !== null) saveLabel();
});
load();
