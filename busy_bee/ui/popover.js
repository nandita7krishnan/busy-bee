function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function cardStateClass(project) {
  if (project.blockers.length > 0) return "state-blocked";
  if (project.questions.length > 0) return "state-question";
  if (project.status === "active") return "state-active";
  return "state-idle";
}

function renderColumn(title, items, className, emptyLabel) {
  const listItems = items.length
    ? items.map((text) => `<li>${escapeHtml(text)}</li>`).join("")
    : `<li class="empty-column">${emptyLabel}</li>`;
  return `<div class="column ${className}"><h4>${title}</h4><ul>${listItems}</ul></div>`;
}

function renderFlagLine(item, type) {
  return `
    <div class="flag-line ${type}">
      <span class="dot"></span>
      <span>${escapeHtml(item.text)}</span>
      <button class="resolve-btn" data-resolve-id="${item.id}" data-resolve-type="${type}">resolve</button>
    </div>
  `;
}

function renderCard(project) {
  const stateClass = cardStateClass(project);
  const hasFlags = project.blockers.length > 0 || project.questions.length > 0;
  const expanded = hasFlags; // resets every open, per spec

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
    <div class="card ${stateClass} ${expanded ? "expanded" : ""}" data-project="${escapeHtml(project.name)}">
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
      if (e.target.closest("[data-open-terminal]") || e.target.closest("[data-resolve-id]")) return;
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

  cardsEl.querySelectorAll("[data-resolve-id]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await window.pywebview.api.resolve_item(parseInt(btn.dataset.resolveId, 10));
      loadProjects();
    });
  });
}

async function loadProjects() {
  const projects = await window.pywebview.api.get_projects();
  render(projects);
}

window.addEventListener("pywebviewready", loadProjects);
