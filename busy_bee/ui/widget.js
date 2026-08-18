async function refreshIcon() {
  document.getElementById("icon").src = await window.pywebview.api.get_widget_icon_data_uri();
}

// A native window drag (easy_drag) still ends in a normal DOM
// mousedown->mouseup on the icon -- browsers fire `click` from that
// regardless of how far the mouse moved in between, since a drag
// here moves the *window*, not any on-page element. So a plain click
// listener alone can't tell "clicked" from "just finished dragging
// the widget across the screen" -- track the mousedown position
// ourselves and only treat it as a real click if the pointer barely
// moved.
//
// Must use screenX/screenY, not clientX/clientY: during the native
// drag the OS moves the window to follow the cursor, so the icon
// stays under the pointer and viewport-relative coordinates barely
// change even for a large drag -- that's what made this pass as a
// "click" intermittently. Screen coordinates aren't affected by the
// window itself moving.
const DRAG_THRESHOLD_PX = 4;
let mouseDownPos = null;

function onMouseDown(e) {
  mouseDownPos = { x: e.screenX, y: e.screenY };
}

function onClick(e) {
  if (!mouseDownPos) return;
  const dx = e.screenX - mouseDownPos.x;
  const dy = e.screenY - mouseDownPos.y;
  mouseDownPos = null;
  if (Math.hypot(dx, dy) > DRAG_THRESHOLD_PX) return; // was a drag, not a click

  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.open_dashboard();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const icon = document.getElementById("icon");
  icon.addEventListener("mousedown", onMouseDown);
  icon.addEventListener("click", onClick);
});

window.addEventListener("pywebviewready", refreshIcon);
