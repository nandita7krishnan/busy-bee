function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

const PROJECT_COLOR_COUNT = 8;

function projectColorClass(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return `proj-${hash % PROJECT_COLOR_COUNT}`;
}

function renderColumn(title, items, className, emptyLabel) {
  const check = className === "done" ? "✓" : "▢"; // ✓ / ▢
  const listItems = items.length
    ? items
        .map((text) => {
          const safe = escapeHtml(text);
          return `<li><span class="check">${check}</span><span class="item-text" title="${safe}">${safe}</span></li>`;
        })
        .join("")
    : `<li class="empty-column">${emptyLabel}</li>`;
  return `<div class="column ${className}"><h4>${title}</h4><ul>${listItems}</ul></div>`;
}

function renderFlagLine(item, type) {
  // No manual "resolve" here -- this should stay a faithful mirror of
  // the actual terminal, not a place that can drift from it. Real
  // resolution happens when the agent calls `dashctl resolve` after
  // the user responds in that terminal. Clicking a flag line just
  // takes you there, same as clicking the project name.
  return `
    <div class="flag-line ${type}" data-open-terminal>
      <span class="dot"></span>
      <span class="item-text">${escapeHtml(item.text)}</span>
      <span class="goto-terminal">open →</span>
    </div>
  `;
}

function renderCard(project) {
  const colorClass = projectColorClass(project.name);
  const hasFlags = project.blockers.length > 0 || project.questions.length > 0;
  const expanded = true; // always expanded by default; chevron can still collapse manually

  const badges = [
    project.blockers.length
      ? `<span class="badge blocker">${project.blockers.length}</span>`
      : "",
    project.questions.length
      ? `<span class="badge question">${project.questions.length}</span>`
      : "",
  ].join("");

  const flagsHtml = hasFlags
    ? `<div class="flags">
        ${project.blockers.map((b) => renderFlagLine(b, "blocker")).join("")}
        ${project.questions.map((q) => renderFlagLine(q, "question")).join("")}
      </div>`
    : "";

  return `
    <div class="card ${colorClass} ${expanded ? "expanded" : ""}" data-project="${escapeHtml(project.name)}">
      <div class="card-header" data-toggle>
        <span class="chevron">&#9656;</span>
        <span class="project-name" data-open-terminal>${escapeHtml(project.name)}</span>
        ${badges}
      </div>
      <div class="card-body">
        <div class="columns">
          ${renderColumn("Done", project.done, "done", "nothing yet")}
          ${renderColumn("Next", project.todo, "todo", "nothing queued")}
        </div>
        ${flagsHtml}
      </div>
    </div>
  `;
}

function render(projects) {
  const cardsEl = document.getElementById("cards");
  const emptyEl = document.getElementById("empty-state");
  if (!projects.length) {
    emptyEl.hidden = false;
    cardsEl.innerHTML = "";
    return;
  }
  emptyEl.hidden = true;
  cardsEl.innerHTML = projects.map(renderCard).join("");

  cardsEl.querySelectorAll("[data-toggle]").forEach((header) => {
    header.addEventListener("click", (e) => {
      if (e.target.closest("[data-open-terminal]")) return;
      header.closest(".card").classList.toggle("expanded");
    });
  });

  cardsEl.querySelectorAll("[data-open-terminal]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      const project = el.closest(".card").dataset.project;
      window.pywebview.api.open_terminal(project);
    });
  });
}

async function loadProjects() {
  const projects = await window.pywebview.api.get_projects();
  render(projects);
}

async function startAutoRefresh() {
  await loadProjects();
  // Matches the aggregator's own poll interval (fetched, not
  // hardcoded, so changing poll_interval_seconds in config.json can't
  // make this drift out of sync with it) -- otherwise this window
  // just sitting open would silently go stale between clicks.
  const intervalSeconds = await window.pywebview.api.get_poll_interval_seconds();
  setInterval(loadProjects, intervalSeconds * 1000);
}

window.addEventListener("pywebviewready", startAutoRefresh);
