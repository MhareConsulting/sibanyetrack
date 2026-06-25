/* SSE live vehicle positions */
window.MyTrackLive = {
  source: null,
  vehicles: [],
  listeners: [],

  /** SSE uses reg/address; mobile API uses registration/last_address — normalize both. */
  normalize(rows) {
    return (rows || []).map((v) => {
      const registration = v.registration || v.reg || v.label || "";
      const last_address = v.last_address || v.address || "";
      const speed = v.speed_kmh;
      const lastSeen = v.last_seen;
      let parked = v.parked;
      if (parked === undefined && lastSeen) {
        const ageSec = (Date.now() - new Date(lastSeen).getTime()) / 1000;
        parked = ageSec <= 900 && (speed == null || speed < 3);
      }
      return {
        ...v,
        registration,
        reg: registration,
        label: v.label || registration,
        last_address,
        address: last_address,
        parked: !!parked,
      };
    });
  },

  start() {
    if (this.source) return;
    this.source = new EventSource("/live/stream/");
    this.source.onmessage = (ev) => {
      try {
        this.vehicles = this.normalize(JSON.parse(ev.data));
        this.listeners.forEach((fn) => fn(this.vehicles));
      } catch (e) {
        console.warn("live parse", e);
      }
    };
    this.source.onerror = () => {
      this.source.close();
      this.source = null;
      setTimeout(() => this.start(), 5000);
    };
  },

  onUpdate(fn) {
    this.listeners.push(fn);
    if (this.vehicles.length) fn(this.vehicles);
  },

  stop() {
    if (this.source) {
      this.source.close();
      this.source = null;
    }
  },
};
