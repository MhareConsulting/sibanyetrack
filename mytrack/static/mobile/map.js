/* MapLibre helpers for mobile dispatcher */
window.MyTrackMap = {
  MAP_STYLES: {
    street: { version: 8, sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '&copy; OpenStreetMap contributors' }}, layers: [{ id: 'osm', type: 'raster', source: 'osm' }] },
    satellite: { version: 8, sources: { sat: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], tileSize: 256, attribution: 'Tiles &copy; Esri' }}, layers: [{ id: 'sat', type: 'raster', source: 'sat' }] },
  },
  map: null,
  markers: {},
  styleKey: "street",

  init(containerId, opts = {}) {
    if (this.map) {
      this.map.remove();
      this.map = null;
      this.markers = {};
    }
    const style = this.MAP_STYLES[this.styleKey] || this.MAP_STYLES.street;
    this.map = new maplibregl.Map({
      container: containerId,
      style,
      center: opts.center || [28.0473, -26.2041],
      zoom: opts.zoom || 11,
      attributionControl: true,
    });
    return this.map;
  },

  setStyle(key) {
    this.styleKey = key;
    if (this.map) this.map.setStyle(this.MAP_STYLES[key] || this.MAP_STYLES.street);
  },

  clearMarkers() {
    Object.values(this.markers).forEach((m) => m.remove());
    this.markers = {};
  },

  updateVehicles(vehicles, selectedId) {
    if (!this.map) return;
    const bounds = new maplibregl.LngLatBounds();
    let hasPoint = false;

    vehicles.forEach((v) => {
      if (v.lat == null || v.lon == null) return;
      hasPoint = true;
      bounds.extend([v.lon, v.lat]);
      const el = document.createElement("div");
      el.className = "m-map-marker";
      if (v.parked || (v.speed_kmh != null && v.speed_kmh < 3)) {
        el.innerHTML = `<div style="width:28px;height:36px;background:#8a2be2;border-radius:50% 50% 50% 0;transform:rotate(-45deg);display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(138,43,226,.45)"><span style="transform:rotate(45deg);color:#fff;font-weight:700;font-size:12px">P</span></div>`;
      } else {
        el.innerHTML = `<div style="width:14px;height:14px;background:#00c8ff;border:3px solid #fff;border-radius:50%;box-shadow:0 1px 6px rgba(0,200,255,.5)"></div>`;
      }
      if (this.markers[v.id]) {
        this.markers[v.id].setLngLat([v.lon, v.lat]);
      } else {
        this.markers[v.id] = new maplibregl.Marker({ element: el })
          .setLngLat([v.lon, v.lat])
          .addTo(this.map);
      }
      if (selectedId === v.id) {
        this.map.flyTo({ center: [v.lon, v.lat], zoom: 15 });
      }
    });

    if (hasPoint && !selectedId && vehicles.length) {
      try {
        this.map.fitBounds(bounds, { padding: 48, maxZoom: 14 });
      } catch (_) {}
    }
  },

  drawRoute(pings, snapped) {
    if (!this.map) return;
    const coords = (snapped && snapped.length >= 2)
      ? snapped
      : pings.filter((p) => p.lon != null).map((p) => [p.lon, p.lat]);
    if (coords.length < 2) return;

    if (this.map.getSource("route")) {
      this.map.getSource("route").setData({
        type: "Feature",
        geometry: { type: "LineString", coordinates: coords },
      });
    } else {
      this.map.on("load", () => this._addRoute(coords));
      if (this.map.loaded()) this._addRoute(coords);
    }
    const bounds = coords.reduce(
      (b, c) => b.extend(c),
      new maplibregl.LngLatBounds(coords[0], coords[0])
    );
    this.map.fitBounds(bounds, { padding: 40 });
  },

  _addRoute(coords) {
    if (this.map.getSource("route")) return;
    this.map.addSource("route", {
      type: "geojson",
      data: { type: "Feature", geometry: { type: "LineString", coordinates: coords } },
    });
    this.map.addLayer({
      id: "route-line",
      type: "line",
      source: "route",
      paint: { "line-color": "#8a2be2", "line-width": 4 },
    });
  },

  locateUser() {
    if (!navigator.geolocation || !this.map) return;
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        this.map.flyTo({ center: [pos.coords.longitude, pos.coords.latitude], zoom: 14 });
      },
      () => MyTrackMobile.toast("Location unavailable")
    );
  },
};
