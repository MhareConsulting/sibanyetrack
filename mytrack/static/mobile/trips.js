window.MyTrackTrips = {
  classification: "",
  vehicleFilter: "",
  dateFilter: "",

  async load() {
    const params = new URLSearchParams();
    if (this.classification) params.set("classification", this.classification);
    if (this.vehicleFilter) params.set("vehicle", this.vehicleFilter);
    if (this.dateFilter) params.set("date", this.dateFilter);
    const q = params.toString() ? `?${params}` : "";
    return MyTrackMobile.api(`/trips/${q}`);
  },

  async toggleClassification(tripId, current) {
    const next = current === "personal" ? "business" : "personal";
    await MyTrackMobile.api(`/trips/${tripId}/classification/`, {
      method: "PATCH",
      body: JSON.stringify({ classification: next }),
    });
    return next;
  },

  downloadUrl() {
    const params = new URLSearchParams();
    if (this.vehicleFilter) params.set("vehicle", this.vehicleFilter);
    if (this.dateFilter) params.set("date", this.dateFilter);
    const q = params.toString();
    return `/intelligence/reports/trips/csv/${q ? "?" + q : ""}`;
  },
};
