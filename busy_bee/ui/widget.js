async function refreshIcon() {
  document.getElementById("icon").src = await window.pywebview.api.get_widget_icon_data_uri();
}

function onIconClick() {
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.open_dashboard();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("icon").addEventListener("click", onIconClick);
});

window.addEventListener("pywebviewready", refreshIcon);
