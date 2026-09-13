/* Install page logic: builds the draggable bookmarklet link + copy button. */
(function () {
  function deviceId() {
    var id = null;
    try { id = localStorage.getItem("lb_device_id"); } catch (e) {}
    if (!id) {
      id = "dev-" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
      try { localStorage.setItem("lb_device_id", id); } catch (e) {}
    }
    return id;
  }
  deviceId();
  fetch("bookmarklet.js", { cache: "no-store" }).then(function (r) { return r.text(); }).then(function (code) {
    var href = "javascript:" + encodeURIComponent(code);
    var btn = document.getElementById("bmBtn");
    if (btn) btn.setAttribute("href", href);
    var cp = document.getElementById("copyBm");
    if (cp) cp.onclick = function () {
      navigator.clipboard.writeText(code).then(function () {
        var o = cp.textContent; cp.textContent = "Copied \u2713 — paste it on the short-link page";
        setTimeout(function () { cp.textContent = o; }, 2500);
      });
    };
  }).catch(function () {
    var cp = document.getElementById("copyBm");
    if (cp) { cp.disabled = true; cp.textContent = "Couldn't load snippet — refresh and retry"; }
  });
})();
