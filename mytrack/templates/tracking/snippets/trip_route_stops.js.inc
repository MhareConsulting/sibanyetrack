/* Shared trip route helpers (dwell / stops). Included inside <script> blocks. */
const TRIP_ROUTE_STOP_SPEED_MAX_KMH = 5;
const TRIP_ROUTE_STOP_MIN_MS = 180000;
const TRIP_ROUTE_STOP_MAX_GAP_MS = 600000;
const TRIP_ROUTE_STOP_MAX_CLUSTER_M = 100;

function tripRouteHaversineM(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const r = Math.PI / 180;
  const dLat = (lat2 - lat1) * r;
  const dLon = (lon2 - lon1) * r;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.asin(Math.sqrt(Math.min(1, a)));
}

function tripRouteFormatDuration(ms) {
  const totalMin = Math.max(0, Math.floor(ms / 60000));
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h > 0) return m > 0 ? `${h} h, ${m} min` : `${h} h`;
  return `${m} min`;
}

function detectTripRouteStops(pings) {
  const sorted = pings
    .filter((p) => p.lat != null && p.lon != null && p.ts)
    .sort((a, b) => new Date(a.ts) - new Date(b.ts));

  const stops = [];
  let cluster = null;

  function isSlow(p) {
    return p.speed_kmh == null || p.speed_kmh <= TRIP_ROUTE_STOP_SPEED_MAX_KMH;
  }

  function flush() {
    if (!cluster || !cluster.length) {
      cluster = null;
      return;
    }
    const t0 = new Date(cluster[0].ts).getTime();
    const t1 = new Date(cluster[cluster.length - 1].ts).getTime();
    if (t1 - t0 < TRIP_ROUTE_STOP_MIN_MS) {
      cluster = null;
      return;
    }
    let sumLat = 0;
    let sumLon = 0;
    cluster.forEach((p) => {
      sumLat += p.lat;
      sumLon += p.lon;
    });
    const n = cluster.length;
    const duration_ms = t1 - t0;
    stops.push({
      lat: sumLat / n,
      lon: sumLon / n,
      duration_ms,
      duration_min: duration_ms / 60000,
    });
    cluster = null;
  }

  for (let i = 0; i < sorted.length; i++) {
    const p = sorted[i];
    const t = new Date(p.ts).getTime();
    const prev = i ? sorted[i - 1] : null;
    const prevT = prev ? new Date(prev.ts).getTime() : t;

    if (prev && t - prevT > TRIP_ROUTE_STOP_MAX_GAP_MS) {
      flush();
      cluster = null;
    }

    if (!isSlow(p)) {
      flush();
      cluster = null;
      continue;
    }

    if (!cluster) {
      cluster = [p];
      continue;
    }

    const anchor = cluster[0];
    const spread = tripRouteHaversineM(anchor.lat, anchor.lon, p.lat, p.lon);
    if (spread > TRIP_ROUTE_STOP_MAX_CLUSTER_M) {
      flush();
      cluster = [p];
      continue;
    }
    cluster.push(p);
  }
  flush();

  stops.forEach((s, idx) => {
    s.index = idx + 1;
    s.durationText = tripRouteFormatDuration(s.duration_ms);
    s.label = `${s.index}\n${s.durationText}`;
  });
  return stops;
}

function tripRouteStopRadiusM(durationMin) {
  const lo = 35;
  const hi = 220;
  const t = Math.min(1, Math.max(0, (durationMin - 3) / 120));
  return lo + (hi - lo) * t;
}

function removeMaplibreTripRouteVisuals(m, idPrefix) {
  const lineSrc = `${idPrefix}-line`;
  const stopSrc = `${idPrefix}-stops`;
  const lineLayer = `${idPrefix}-line-track`;
  const legacy = [
    `${idPrefix}-stops-text`,
    `${idPrefix}-stops-circle`,
    lineLayer,
    `${idPrefix}-line-dir`,
    `${idPrefix}-line-base`,
    `${idPrefix}-line-casing`,
    `${idPrefix}-line-outline`,
  ];
  legacy.forEach((lid) => {
    if (m.getLayer(lid)) m.removeLayer(lid);
  });
  if (m.getSource(stopSrc)) m.removeSource(stopSrc);
  if (m.getSource(lineSrc)) m.removeSource(lineSrc);
}

function addMaplibreTripRouteVisuals(m, idPrefix, pings, color, snappedCoords) {
  if (!m.isStyleLoaded()) return;
  const rawCoords = pings
    .map((p) => [p.lon, p.lat])
    .filter((c) => c[0] != null && c[1] != null);
  if (rawCoords.length < 2) return;
  const coords = (snappedCoords && snappedCoords.length >= 2) ? snappedCoords : rawCoords;
  const lineSrc = `${idPrefix}-line`;
  const lineLayer = `${idPrefix}-line-track`;
  const stopSrc = `${idPrefix}-stops`;
  if (m.getSource(lineSrc)) return;

  const stops = detectTripRouteStops(pings);
  const stopFc = {
    type: 'FeatureCollection',
    features: stops.map((s) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
      properties: { duration_min: s.duration_min, label: s.label },
    })),
  };

  m.addSource(lineSrc, {
    type: 'geojson',
    data: { type: 'Feature', geometry: { type: 'LineString', coordinates: coords } },
  });
  m.addLayer({
    id: lineLayer,
    type: 'line',
    source: lineSrc,
    layout: {
      'line-cap': 'round',
      'line-join': 'round',
    },
    paint: {
      'line-color': color,
      'line-width': 3,
      'line-opacity': 0.85,
    },
  });
  m.addSource(stopSrc, { type: 'geojson', data: stopFc });
  m.addLayer({
    id: `${idPrefix}-stops-circle`,
    type: 'circle',
    source: stopSrc,
    paint: {
      'circle-radius': [
        'interpolate',
        ['linear'],
        ['get', 'duration_min'],
        0,
        14,
        5,
        20,
        30,
        34,
        180,
        48,
      ],
      'circle-color': 'rgba(253, 224, 71, 0.4)',
      'circle-stroke-color': '#ea580c',
      'circle-stroke-width': 2,
      'circle-opacity': 1,
    },
  });
  try {
    m.addLayer({
      id: `${idPrefix}-stops-text`,
      type: 'symbol',
      source: stopSrc,
      layout: {
        'text-field': ['get', 'label'],
        'text-size': 11,
        'text-font': ['Noto Sans Bold'],
        'text-max-width': 8,
        'text-line-height': 1.15,
        'text-anchor': 'center',
        'text-allow-overlap': true,
        'text-ignore-placement': true,
      },
      paint: {
        'text-color': '#111827',
        'text-halo-color': '#ffffff',
        'text-halo-width': 1.5,
      },
    });
  } catch (_) {
    /* labels optional if glyphs missing */
  }
}

function leafRebuildRouteVisuals(routeGroup, pings, vehicleLatLng, destLatLng) {
  if (!routeGroup || typeof L === 'undefined') return;
  routeGroup.clearLayers();
  const list = (pings || []).filter((p) => p.lat != null && p.lon != null && p.ts);
  const latlngs = list.map((p) => [p.lat, p.lon]);
  if (latlngs.length >= 2) {
    L.polyline(latlngs, {
      color: '#8A2BE2',
      weight: 3,
      opacity: 0.85,
      lineJoin: 'round',
      lineCap: 'round',
    }).addTo(routeGroup);
    detectTripRouteStops(list).forEach((s) => {
      L.circle([s.lat, s.lon], {
        radius: tripRouteStopRadiusM(s.duration_min),
        color: '#ea580c',
        weight: 2,
        fillColor: '#fde047',
        fillOpacity: 0.32,
      }).addTo(routeGroup);
      const html = `<div style="text-align:center;line-height:1.12;font-family:system-ui,sans-serif">` +
        `<div style="font-weight:800;font-size:12px;color:#111;text-shadow:0 0 3px #fff,0 0 6px #fff">${s.index}</div>` +
        `<div style="font-weight:600;font-size:10px;color:#111;text-shadow:0 0 3px #fff">${s.durationText}</div></div>`;
      L.marker([s.lat, s.lon], {
        icon: L.divIcon({ className: '', html, iconSize: [80, 36], iconAnchor: [40, 18] }),
        interactive: false,
      }).addTo(routeGroup);
    });
  }
  if (
    vehicleLatLng &&
    destLatLng &&
    vehicleLatLng[0] != null &&
    destLatLng[0] != null
  ) {
    const a = L.latLng(vehicleLatLng[0], vehicleLatLng[1]);
    const b = L.latLng(destLatLng[0], destLatLng[1]);
    L.polyline([a, b], {
      color: '#8A2BE2',
      weight: 2,
      opacity: 0.7,
      dashArray: '6 6',
      lineCap: 'round',
    }).addTo(routeGroup);
  }
}
