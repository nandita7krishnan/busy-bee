function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// The palette slot comes from Python (db.ensure_color_index, surfaced
// as `color` by Api.get_projects), which allocates against the slots
// already in use. This used to hash the project name here instead --
// which, knowing nothing about the other projects on screen, handed
// two of them the same color. The same index drives the project's
// Terminal tab tint (busy_bee/colors.py), so card and terminal still
// match; --proj-N in popover.css must stay in step with PROJECT_COLORS
// there.
const PROJECT_COLOR_COUNT = 8;

function projectColorClass(project) {
  const index = Number.isInteger(project.color) ? project.color : 0;
  return `proj-${index % PROJECT_COLOR_COUNT}`;
}

// `items` is either a list of plain strings (session-level done/todo --
// always agent-logged, never editable) or a list of {id, text} task
// objects (project-level done/todo -- placeholder tasks, or manual
// tasks merged onto a real project's card). `interactive` renders a
// clickable/keyboard-toggleable checkbox in place of the inert glyph --
// only ever true for a placeholder card's own columns (see decision 3:
// manual checkboxes are placeholder-only, real project cards stay a
// read-only mirror of agent activity).
function renderColumn(title, items, className, emptyLabel, interactive) {
  const check = className === "done" ? "✓" : "▢"; // ✓ / ▢
  const listItems = items.length
    ? items
        .map((item) => {
          const entry = typeof item === "string" ? { text: item } : item;
          const safe = escapeHtml(entry.text);
          const checkSpan = interactive
            ? `<span class="check check-toggle" data-toggle-task data-task-id="${escapeHtml(entry.id)}" role="checkbox" tabindex="0" aria-checked="${className === "done"}">${check}</span>`
            : `<span class="check">${check}</span>`;
          // Same `interactive` gate as the checkbox: a manual task can
          // be deleted because the user typed it, an agent-logged one
          // can't -- the card would then disagree with the terminal
          // it's mirroring. Hidden until the row is hovered/focused so
          // a column of tasks doesn't read as a column of × buttons.
          const deleteSpan = interactive
            ? `<span class="task-delete" data-delete-task data-task-id="${escapeHtml(entry.id)}" role="button" tabindex="0" title="Delete this task" aria-label="Delete task">&times;</span>`
            : "";
          return `<li>${checkSpan}<span class="item-text" title="${safe}">${safe}</span>${deleteSpan}</li>`;
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

function renderPlaceholderCard(project) {
  const colorClass = projectColorClass(project);
  const error = createFolderErrors[project.name];
  const errorHtml = error
    ? `<div class="form-error">${escapeHtml(error)}</div>`
    : "";

  // "Create folder" sits in the header where a real card's clickable
  // title would be, rather than as its own row down in the body -- it
  // IS this card's primary action, and it replaces the purely
  // informational "no folder" pill that used to say the same thing
  // without offering to do anything about it.
  //
  // Rendered collapsed: a placeholder is usually a thing you jotted
  // down and won't touch again for a while, so it shouldn't take up as
  // much room as a project with a live session. "+ Task" on the right
  // edge is what keeps it one click to add to anyway -- it expands the
  // card and drops the cursor straight in the input.
  return `
    <div class="card ${colorClass}" data-project="${escapeHtml(project.name)}" data-placeholder="true">
      <div class="card-header" data-toggle>
        <span class="chevron">&#9656;</span>
        <div class="title-row">
          <span class="project-name">${escapeHtml(project.name)}</span>
          <span class="create-folder" data-create-folder
                title="Creates the folder, registers this project on the dashboard, and starts tracking it.">
            Create folder&hellip;
          </span>
        </div>
        <span class="add-task-btn" data-focus-task title="Add a task">+ Task</span>
        <span class="delete-project-btn" data-delete-project role="button" tabindex="0"
              title="Delete this card" aria-label="Delete this card">&times;</span>
      </div>
      <div class="card-body">
        <div class="columns">
          ${renderColumn("Done", project.done, "done", "nothing yet", true)}
          ${renderColumn("Next", project.todo, "todo", "nothing queued", true)}
        </div>
        <form class="task-add" data-add-task>
          <input class="task-input" placeholder="Add a task" autocomplete="off" />
        </form>
        ${errorHtml}
      </div>
    </div>
  `;
}

function renderRealCard(project) {
  const colorClass = projectColorClass(project);
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

  // With one live session (the common case) the header still resumes
  // it directly, same as before sessions existed. With several, which
  // one the header itself should resume is ambiguous, so it defers to
  // each session block's own "open" affordance instead.
  const titleTtyAttr =
    project.sessions.length === 1 ? ` data-tty="${escapeHtml(project.sessions[0].tty)}"` : "";
  const titleOpensTerminal = project.sessions.length <= 1;

  // Once a project is real, its card goes back to being purely a
  // mirror of agent activity -- handed-off tasks are the agent's now
  // (they're in status.json and it was prompted with them), and
  // declined ones stay on the dashboard only until the folder exists.
  // A separate "From the dashboard" block here just duplicated what
  // the session's own Next column already shows once work starts.
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

function renderCard(project) {
  return project.placeholder ? renderPlaceholderCard(project) : renderRealCard(project);
}

// The 5s Python-driven refresh (see loadProjects below) calls render()
// on a full, fresh project list every time. That's fine for a purely
// read-only card, but this feature adds text inputs -- and render()
// rebuilds #cards' innerHTML from scratch every call, which would
// destroy whatever the user is mid-typing (and its focus) on every
// single tick. Rather than reach for a JS setInterval instead (tried
// once already for this exact refresh loop and found to silently stall
// -- see the comment at the bottom of this file), the render is simply
// deferred while a card input has focus, and replayed the moment focus
// leaves it. Nothing is lost either way: the next 5s tick will supply
// an equally-fresh list if this one goes stale while deferred.
let pendingProjects = null;

// Keyed by project name -- set on a failed "Create folder" (cancelling
// the folder picker is not an error and isn't stored here), read by
// renderPlaceholderCard, and cleared the moment that card next tries
// again. A plain variable, not part of the project data itself, since
// get_projects() has no reason to know about a UI-local failure.
const createFolderErrors = {};

function render(projects) {
  const cardsEl = document.getElementById("cards");
  const emptyEl = document.getElementById("empty-state");

  const active = document.activeElement;
  if (active && active.closest && active.closest("#cards input")) {
    pendingProjects = projects;
    return;
  }
  pendingProjects = null;

  if (!projects.length) {
    emptyEl.hidden = false;
    cardsEl.innerHTML = "";
    return;
  }
  emptyEl.hidden = true;

  // Whatever the user last toggled a card to, remembered across the 5s
  // refresh that rebuilds all this markup. Recorded as the actual state
  // rather than just "which ones are collapsed", because the two card
  // types default opposite ways -- real cards start expanded,
  // placeholders start collapsed -- so either direction can be the
  // deviation worth preserving.
  const wasExpanded = new Map(
    [...cardsEl.querySelectorAll(".card")].map((c) => [
      c.dataset.project,
      c.classList.contains("expanded"),
    ])
  );

  cardsEl.innerHTML = projects.map(renderCard).join("");

  cardsEl.querySelectorAll(".card").forEach((card) => {
    const previous = wasExpanded.get(card.dataset.project);
    // Absent => a card that wasn't on screen last render; leave it at
    // whatever default its own template chose.
    if (previous !== undefined) card.classList.toggle("expanded", previous);
  });

  cardsEl.querySelectorAll("[data-toggle]").forEach((header) => {
    header.addEventListener("click", (e) => {
      // These live in the header and have their own handlers -- a click
      // on any of them shouldn't also toggle the card underneath it.
      if (e.target.closest("[data-open-terminal]")) return;
      if (e.target.closest("[data-create-folder]")) return;
      if (e.target.closest("[data-focus-task]")) return;
      if (e.target.closest("[data-delete-project]")) return;
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

  cardsEl.querySelectorAll("[data-focus-task]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      const card = el.closest(".card");
      card.classList.add("expanded");
      // Focusing also parks the deferred-render guard on this card (see
      // render()), so the 5s refresh won't yank the input away while
      // the user is typing into the box it just opened for them.
      card.querySelector(".task-input").focus();
    });
  });

  cardsEl.querySelectorAll("[data-add-task]").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = form.querySelector(".task-input");
      const text = input.value.trim();
      if (!text) return;
      const project = form.closest(".card").dataset.project;
      const result = await window.pywebview.api.add_placeholder_task(project, text);
      if (result.ok) {
        input.value = "";
        // Without this, the input (now empty, nothing left to protect)
        // still holds focus, and render()'s "don't clobber what's being
        // typed" guard defers this very refresh -- the new task then
        // wouldn't actually appear until focus left the box some other
        // way, reading as a stuck/laggy add.
        input.blur();
        loadProjects();
      }
    });
  });

  cardsEl.querySelectorAll("[data-toggle-task]").forEach((el) => {
    const toggle = async () => {
      const card = el.closest(".card");
      const project = card.dataset.project;
      const taskId = el.dataset.taskId;
      const nowDone = el.getAttribute("aria-checked") !== "true";
      await window.pywebview.api.set_placeholder_task_done(project, taskId, nowDone);
      loadProjects();
    };
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      toggle();
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        e.stopPropagation();
        toggle();
      }
    });
  });

  cardsEl.querySelectorAll("[data-delete-task]").forEach((el) => {
    const remove = async () => {
      const card = el.closest(".card");
      await window.pywebview.api.delete_placeholder_task(
        card.dataset.project,
        el.dataset.taskId
      );
      loadProjects();
    };
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      remove();
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        e.stopPropagation();
        remove();
      }
    });
  });

  cardsEl.querySelectorAll("[data-delete-project]").forEach((el) => {
    const remove = async () => {
      // A card with tasks puts up a native confirm on the Python side
      // (Api.remove_placeholder_project); an empty one just goes. Either
      // way the refresh below is what makes it disappear.
      if (el.classList.contains("disabled")) return; // that confirm is a
      // modal dialog, so the same one-at-a-time rule as "Create folder"
      // applies while it's up
      el.classList.add("disabled");
      try {
        await window.pywebview.api.remove_placeholder_project(
          el.closest(".card").dataset.project
        );
      } finally {
        loadProjects();
      }
    };
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      remove();
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        e.stopPropagation();
        remove();
      }
    });
  });

  cardsEl.querySelectorAll("[data-create-folder]").forEach((el) => {
    el.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (el.classList.contains("disabled")) return; // guards pywebview's
      // per-window folder-dialog semaphore against a second concurrent call
      el.classList.add("disabled");
      const project = el.closest(".card").dataset.project;
      delete createFolderErrors[project];
      try {
        const result = await window.pywebview.api.activate_placeholder_project(project);
        if (!result.ok && !result.cancelled) {
          createFolderErrors[project] = result.error || "couldn't create the folder";
        }
      } finally {
        loadProjects();
      }
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

// Deferred re-render (see the comment above render()) is replayed as
// soon as focus leaves whatever input inside #cards was blocking it.
document.getElementById("cards").addEventListener("focusout", () => {
  if (pendingProjects) {
    const toApply = pendingProjects;
    requestAnimationFrame(() => render(toApply));
  }
});

const addProjectBtn = document.getElementById("add-project-btn");
const addProjectInput = document.getElementById("new-project-name");
const addProjectError = document.getElementById("add-project-error");

async function submitNewProject() {
  const name = addProjectInput.value.trim();
  if (!name) return;
  const result = await window.pywebview.api.add_placeholder_project(name);
  if (result.ok) {
    addProjectInput.value = "";
    addProjectError.hidden = true;
    loadProjects();
  } else {
    addProjectError.textContent = result.error || "couldn't add that project";
    addProjectError.hidden = false;
  }
}

// Bound once, outside render() -- #add-project lives outside #cards so
// it's never wiped by the 5s refresh, and re-binding these on every
// render (if it were inside #cards) would stack duplicate listeners.
addProjectBtn.addEventListener("click", submitNewProject);
addProjectInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    submitNewProject();
  }
});
