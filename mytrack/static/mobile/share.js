window.MyTrackShare = {
  async shareLocation(vehicleId, note) {
    const data = await MyTrackMobile.api("/share/location/", {
      method: "POST",
      body: JSON.stringify({ vehicle_id: vehicleId, note: note || "Shared location" }),
    });
    const payload = { title: "Vehicle location", text: data.url, url: data.url };
    if (navigator.share) {
      try {
        await navigator.share(payload);
        return data.url;
      } catch (e) {
        if (e.name === "AbortError") return null;
      }
    }
    await navigator.clipboard.writeText(data.url);
    MyTrackMobile.toast("Link copied to clipboard");
    return data.url;
  },

  async shareAsset(vehicleId) {
    return this.shareLocation(vehicleId, "Asset tracking link");
  },
};
