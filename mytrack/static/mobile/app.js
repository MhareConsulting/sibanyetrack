/* Global mobile app helpers */
window.MyTrackMobile = {
  csrfToken: "",
  bootstrap: null,
  selectedVehicleId: null,

  async api(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }
    if (["POST", "PATCH", "PUT", "DELETE"].includes((options.method || "GET").toUpperCase())) {
      headers["X-CSRFToken"] = this.csrfToken;
    }
    const res = await fetch(`/api/mobile${path}`, { credentials: "same-origin", ...options, headers });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Request failed");
    }
    return res.json();
  },

  toast(msg) {
    let el = document.getElementById("m-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "m-toast";
      el.className = "m-toast";
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 2800);
  },

  formatDt(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleString("en-ZA", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  },

  /** Fleet truck icon from shared Mhare icon registry (icons.js). */
  vehicleIconHtml(className = "m-icon-truck") {
    if (window.MhareIcons) {
      return MhareIcons.iconHtml("truck", className);
    }
    return "";
  },

  /** @deprecated use vehicleIconHtml */
  carSvg() {
    return this.vehicleIconHtml();
  },
};

document.addEventListener("DOMContentLoaded", async () => {
  try {
    const data = await MyTrackMobile.api("/bootstrap/");
    MyTrackMobile.bootstrap = data;
    MyTrackMobile.csrfToken = data.csrf_token;
    document.dispatchEvent(new CustomEvent("mytrack:bootstrap", { detail: data }));
  } catch (e) {
    console.warn("bootstrap failed", e);
  }

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/mobile/sw.js", { scope: "/app/" }).catch(() => {});
  }

  const menuBtn = document.getElementById("m-menu-btn");
  const menuOverlay = document.getElementById("m-menu-overlay");
  if (menuBtn && menuOverlay) {
    menuBtn.addEventListener("click", () => menuOverlay.classList.add("open"));
    menuOverlay.addEventListener("click", (e) => {
      if (e.target === menuOverlay) menuOverlay.classList.remove("open");
    });
  }
});
