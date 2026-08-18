function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// Kept identical to busy_bee/colors.py, which also colors each
// project's live Terminal tabs to match -- if you touch this hash or
// palette, touch both.
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
  // takes you there, same as clicking the project name -- to that
  // item's own session if it still has one, else the project's last
  // known terminal.
  const ttyAttr = item.tty ? ` data-tty="${escapeHtml(item.tty)}"` : "";
  return `
    <div class="flag-line ${type}" data-open-terminal${ttyAttr}>
      <span class="dot"></span>
      <span class="item-text">${escapeHtml(item.text)}</span>
    </div>
  `;
}

function renderSession(session, index) {
  const sessionBlockers = session.blockers || [];
  const sessionQuestions = session.questions || [];
  const hasFlags = sessionBlockers.length > 0 || sessionQuestions.length > 0;

  const badges = [
    sessionBlockers.length ? `<span class="badge blocker">${sessionBlockers.length}</span>` : "",
    sessionQuestions.length ? `<span class="badge question">${sessionQuestions.length}</span>` : "",
  ].join("");

  const flagsHtml = hasFlags
    ? `<div class="flags">
        ${sessionBlockers.map((b) => renderFlagLine(b, "blocker")).join("")}
        ${sessionQuestions.map((q) => renderFlagLine(q, "question")).join("")}
      </div>`
    : "";

  return `
    <div class="session-block">
      <div class="session-header" data-open-terminal data-tty="${escapeHtml(session.tty)}">
        <span class="live-dot"></span>
        <span class="session-label" title="${escapeHtml(session.name || `Session ${index + 1}`)}">${escapeHtml(session.name || `Session ${index + 1}`)}</span>
        ${badges}
      </div>
      <div class="session-columns">
        ${renderColumn("Done", session.done, "done", "nothing yet")}
        ${renderColumn("Next", session.todo, "todo", "nothing queued")}
      </div>
      ${flagsHtml}
    </div>
  `;
}

function renderCard(project) {
  const colorClass = projectColorClass(project.name);
  const hasFlags = project.blockers.length > 0 || project.questions.length > 0;
  const hasSessions = project.sessions.length > 0;
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

  const summaryHtml = project.summary
    ? `<span class="summary-text" title="${escapeHtml(project.summary)}">${escapeHtml(project.summary)}</span>`
    : "";

  // With one live session (the common case) the header still resumes
  // it directly, same as before sessions existed. With several, which
  // one the header itself should resume is ambiguous, so it defers to
  // each session block's own "open" affordance instead.
  const titleTtyAttr =
    project.sessions.length === 1 ? ` data-tty="${escapeHtml(project.sessions[0].tty)}"` : "";
  const titleOpensTerminal = project.sessions.length <= 1;

  const body = hasSessions
    ? `<div class="sessions-row">${project.sessions.map(renderSession).join("")}</div>`
    : `<div class="columns">
        ${renderColumn("Done", project.done, "done", "nothing yet")}
        ${renderColumn("Next", project.todo, "todo", "nothing queued")}
      </div>`;

  return `
    <div class="card ${colorClass} ${expanded ? "expanded" : ""}" data-project="${escapeHtml(project.name)}">
      <div class="card-header" data-toggle>
        <span class="chevron">&#9656;</span>
        <div class="title-row" ${titleOpensTerminal ? `data-open-terminal${titleTtyAttr}` : ""}>
          <span class="project-name">${escapeHtml(project.name)}</span>
          ${summaryHtml}
        </div>
        ${badges}
      </div>
      <div class="card-body">
        ${body}
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
      const tty = el.dataset.tty || null;
      window.pywebview.api.open_terminal(project, tty);
    });
  });
}

async function loadProjects() {
  const projects = await window.pywebview.api.get_projects();
  render(projects);
}

// Periodic refresh is driven from the Python side (BusyBeeApp's
// rumps.Timer calls window.evaluate_js("window.loadProjects()") every
// 5s) rather than a JS-side setInterval here -- that was tried first
// and turned out unreliable in practice (confirmed live: the tray
// badge, driven by that same Python timer, kept updating correctly
// the whole time a JS setInterval sat silently stalled). This only
// needs to handle the initial load.
window.addEventListener("pywebviewready", loadProjects);
