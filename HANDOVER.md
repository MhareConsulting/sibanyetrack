# myTrack — System Handover Document

**Prepared:** May 2026  
**Organisation:** MhareConsulting / MhareTech  
**Production URL:** https://track.mharetech.co.za  
**Repository:** https://github.com/MhareConsulting/myTrack

---

## 1. What is myTrack?

myTrack is a proprietary fleet management and telematics platform built for MhareTech. It ingests live GPS position data from tracking hardware in the field, processes it into trips, alerts, and fuel analytics, and presents the results through a web dashboard used by fleet managers and dispatchers.

The platform is multi-tenant — it supports multiple organisations, each with their own vehicles, users, depots, and settings, all isolated from one another within the same database.

**Core capabilities:**

- Live GPS tracking dashboard with real-time vehicle positions
- Automatic trip reconstruction from GPS pings
- Fuel probe monitoring with per-tank calibration (strapping table)
- Fuel event detection: refuels, theft, drains, probe faults, excess consumption
- Speeding and idle alerts
- Geofence enter/exit events
- Driver management with licence and PDP expiry tracking
- Vehicle compliance: inspection logs, document expiry, service schedules
- Video telematics: dashcam clip ingestion and alert correlation
- Customer delivery tracking (shareable public link)
- Fleet intelligence dashboard: cost analysis, trip reporting, driver scoring
- **Mobile dispatcher PWA** (`/app/`) — installable on iPhone; live map, assets, trips, track replay

---

## 2. Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Web framework | Django 4.2 |
| API framework | Django REST Framework 3.15 |
| Database | PostgreSQL 16 |
| WSGI server | Gunicorn 21 with Gevent workers |
| Static files | Whitenoise (served from the container) |
| Frontend | Django templates + HTMX (no JavaScript framework) |
| GPS middleware | Traccar (open-source, runs as a sidecar container) |
| Email | Azure Communication Services |
| Video storage | Local filesystem or AWS S3 (configurable) |
| Containerisation | Docker + Docker Compose |
| CI/CD | GitHub Actions (deploy on push to `master`) |
| Brute-force protection | django-axes |
| Timezone | Africa/Johannesburg (SAST, UTC+2) |

---

## 3. Infrastructure Architecture

### 3.1 Production deployment

The production server runs three Docker containers managed by `docker-compose.prod.yml`:

```
Internet
    │
    ▼
[ Nginx / reverse proxy ]  (assumed, not in repo — operator-managed)
    │
    ├─► Port 8001  ──►  [ web container ]       Django / Gunicorn
    │                       │
    │                       ▼
    │                   [ db container ]         PostgreSQL 16
    │
    └─► Port 5027  ──►  [ traccar container ]    Teltonika FMB/FMC
        Port 5055          │                     OsmAnd / HTTP
        Port 5001          │                     GT06
        Port 5013          │                     TK103
        Port 5023          │                     Queclink GL200/GL300
        Port 5093          └──► POST /api/ingest/traccar/  ──► web
```

**web container:**
- Image built from `Dockerfile` using Python 3.12-slim
- Runs `gunicorn` with 5 gevent workers, bound on port 8001
- Static files collected into `/app/static_collected` at build time and served by Whitenoise
- Reads all configuration from `.env` file

**db container:**
- PostgreSQL 16 Alpine
- Data persisted in a named Docker volume `pgdata`
- Not exposed to the internet; only reachable by the `web` container

**traccar container:**
- Traccar open-source GPS server (latest tag)
- Decodes hardware tracker protocols and forwards parsed positions to the `web` container via HTTP POST
- Config templated from `traccar/traccar.xml.tpl` — the `INGEST_API_TOKEN` is injected at deploy time
- Tracker device ports exposed to the internet for GPS hardware to connect

### 3.2 Development environment

`docker-compose.yml` adds:
- PostgreSQL exposed on host port 5433 (avoids clash with a local postgres)
- Traccar with the same port mapping
- web container built from local source

### 3.3 CI/CD pipeline

File: `.github/workflows/deploy.yml`

Triggers on every push to `master`. Steps:
1. SSH into the production server using a stored key (`secrets.SSH_PRIVATE_KEY`)
2. `git pull` on `~/mytrack`
3. Regenerate `traccar/traccar.xml` from the template with the current `INGEST_API_TOKEN`
4. `docker compose up --build -d web` — rebuilds and restarts only the web container

**Important:** The pipeline does not run `manage.py migrate` automatically. After any deployment that includes a migration, you must SSH into the server and run:

```bash
docker compose exec web python manage.py migrate
```

**CSRF 403 on forms (e.g. Organisation settings, geofences):** Production settings (`prod.py`) assume TLS is terminated at nginx and set `SECURE_PROXY_SSL_HEADER` / `USE_X_FORWARDED_HOST` when `DJANGO_BEHIND_REVERSE_PROXY` is true (default). Ensure nginx forwards `X-Forwarded-Proto: https` (and typically `Host`) to the web container. If problems persist, set `DJANGO_CSRF_TRUSTED_ORIGINS=https://your-public-host` in `.env`.

### 3.4 Scheduled email commands (no SSH)

Dispatcher and admin notification emails are sent by the same Django functions whether you use **HTTPS triggers** or **shell cron**.

**Preferred (no SSH on the server):** set `CRON_EMAIL_TRIGGER_TOKEN` in production `.env` to a long random secret. GitHub Actions (or any HTTPS client) can `POST` to:

`{SITE_URL}/api/cron/email-jobs/`

with header `Authorization: Bearer <CRON_EMAIL_TRIGGER_TOKEN>` and JSON body `{"job":"digest"}`, `"weekly"`, `"monthly"`, or `"expiry"`. If the token is unset, the endpoint returns **503** (disabled). Wrong token returns **401**. The route is throttled (10/hour per client IP).

Repository workflow [email-schedule.yml](.github/workflows/email-schedule.yml) runs daily at **05:05 UTC** (~07:05 SAST) and sends digest + expiry; on **Mondays UTC** it also sends the weekly summary; on the **1st UTC** it also sends the monthly summary. Configure GitHub repository secrets **`SITE_URL`** (no trailing slash required) and **`CRON_EMAIL_TRIGGER_TOKEN`** (must match production `.env`).

**Org admin UI:** under **Tenancy → Organisation settings** (`/tenancy/settings/`), admins can enable/disable each scheduled email type per organisation and set optional **CC** addresses (comma-separated). Dispatchers cannot edit these flags; they still receive mail when they have the Dispatcher role and an email, unless the org disables that job entirely.

**Fallback (SSH / docker on host):** management commands are unchanged:

| Command | Suggested cadence | Purpose |
|--------|---------------------|---------|
| `python manage.py send_alert_digest` | Daily (e.g. 07:00) | Unresolved alerts from the last 24 hours |
| `python manage.py send_weekly_summary` | Weekly (e.g. Monday 07:00) | Rolling 7-day fleet, safety, and video rollup |
| `python manage.py send_monthly_summary` | Monthly (e.g. 1st 07:00) | Previous calendar month fleet and safety rollup |
| `python manage.py send_expiry_warnings` | Daily | Licence, PDP, and vehicle document expiry thresholds |

Examples (host paths and compose project name may differ):

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py send_alert_digest
docker compose -f docker-compose.prod.yml exec web python manage.py send_weekly_summary
docker compose -f docker-compose.prod.yml exec web python manage.py send_monthly_summary
```

Use `--dry-run` on any of these commands to print recipients without sending email.

---

## 4. Django Application Structure

The project lives under `mytrack/` with a standard Django layout.

### 4.1 Settings

| File | Purpose |
|---|---|
| `mytrack/config/settings/base.py` | All settings; reads from `.env` via `django-environ` |
| `mytrack/config/settings/prod.py` | Production overrides (imports base) |
| `mytrack/config/urls.py` | Root URL routing |
| `mytrack/config/wsgi.py` | WSGI entry point for Gunicorn |

All sensitive values (secret key, DB password, API tokens) come from environment variables defined in `.env`. See `.env.example` for the full list.

### 4.2 Django apps

```
mytrack/
├── tenancy/          Organisation, Depot, User, Role, UserDepotAccess
├── vehicles/         Vehicle, VehicleState, Device, VehicleDepotAssignment
├── tracking/         GPSPing, TrackedTrip, Alert, DeliveryShare  +  ingest endpoints
├── fuel/             FuelReading, FuelEvent, TankCalibration, CalibrationPoint
├── drivers/          Driver, DriverScore
├── geofences/        Geofence, GeofenceEvent, VehicleGeofenceState
├── intelligence/     Dashboard views, fleet cost, trip reports, driver scoring
├── compliance/       InspectionLog, VehicleDocument, ServiceSchedule
├── notifications/    Email dispatch (Azure ACS)
└── video_telematics/ VideoChannel, VideoAsset, VideoUploadIntent, ClipRequest
```

---

## 5. Data Model

### 5.1 Tenancy layer

**Organisation**
The root of every data boundary. Every vehicle, user, and alert belongs to an organisation.

| Field | Notes |
|---|---|
| `name`, `slug` | Display name and URL-safe identifier |
| `speed_limit_kmh` | Fleet-wide speeding threshold |
| `fuel_price_zar` | Fuel cost per litre for fleet cost calculations |
| `idle_burn_rate_lph` | Litres per hour burned at idle |
| `seat_limit` | Maximum licensed user accounts |
| `fuel_refuel_threshold_litres` | Minimum level rise to classify as a refuel |
| `fuel_theft_threshold_litres` | Minimum level drop to trigger theft detection |
| `fuel_theft_speed_max_kmh` | Speed threshold: below = theft, above = drain |

**User** extends Django's `AbstractUser`. Fields:
- `organisation` FK — which org this user belongs to
- `role` — Admin, Dispatcher, or Viewer
- `consumes_license` — whether this user counts toward `seat_limit`

**Depot** — a physical location (yard, branch) within an organisation. Has GPS coordinates and opening hours. Users can be restricted to specific depots via `UserDepotAccess`.

### 5.2 Vehicles layer

**Vehicle** — the central asset record.

| Field | Notes |
|---|---|
| `registration` | Primary identifier; must match `deviceName` in Traccar |
| `label` | Human-friendly display name |
| `home_depot` | Default depot for this vehicle |
| `fuel_tank_capacity_litres` | Used to convert % readings to litres (fallback when no calibration) |
| `expected_fuel_lper100km` | Baseline for excess consumption detection |

**VehicleState** — one row per vehicle, upserted on every GPS ping. Stores the latest lat/lon, speed, heading, driver name, and last seen timestamp. This is what the live map reads.

**Device** — the physical GPS tracker unit (IMEI, model name, phone number). One-to-one with Vehicle when assigned. `status` property returns `online` (<2 min), `stale` (<10 min), or `offline`.

**VehicleDepotAssignment** — records vehicle borrows or transfers between depots with start/end dates. `Vehicle.current_depot` reads this to determine where the vehicle is right now.

### 5.3 Tracking layer

**GPSPing** — immutable record of every received GPS position. Never modified after creation. Indexed on `(vehicle, device_timestamp)` and `(vehicle, received_at)`.

**TrackedTrip** — auto-reconstructed movement segment. A new trip is opened when a ping arrives more than 15 minutes after the previous one (`GAP_MINUTES = 15`). Stores start/end coordinates, distance, max speed, and ping count.

**Alert** — any detected rule violation. Kinds:
- `speeding`, `idle`
- `fuel_theft`, `fuel_drain`, `probe_fault`, `excess_consumption`
- `harsh_braking`, `harsh_accel`, `lane_departure`, `fatigue`, `phone_use`, `seatbelt`
- `camera_event`

**DeliveryShare** — a UUID-tokenised public tracking link emailed to a customer. Has expiry and completion state.

### 5.4 Fuel layer

**FuelReading** — one record per GPS ping that carries fuel data.

| Field | Notes |
|---|---|
| `fuel_level_litres` | Calibrated, processed level |
| `raw_sensor_value` | Pre-calibration probe output (stored for diagnostics) |
| `speed_kmh`, `lat`, `lon` | Snapshot from the ping |
| `tracked_trip` | FK to the trip in progress when this reading was recorded |

**FuelEvent** — detected fuel anomaly (refuel, theft, drain, probe fault, excess consumption). Operators can acknowledge theft/drain events after investigation.

**TankCalibration** — one-to-one with Vehicle. Stores the empirical strapping table from the Fuel Calibration tool:
- `bottom_blind_litres` — fuel below the probe tip that reads as zero
- `top_blind_litres` — headroom above the probe's maximum reach

**CalibrationPoint** — individual (raw_value, litres) data points within a strapping table. Ordered by `raw_value`. At least 2 are required to activate calibration.

### 5.5 Other layers

**Geofence** — polygon defined as `[[lon, lat], ...]` pairs. Uses ray-casting for point-in-polygon. `check_geofences()` is called on every ingest ping; enter/exit events are stored in `GeofenceEvent`.

**Driver** — holds SA ID, licence code and expiry, PDP number and expiry, default vehicle assignment. `licence_status` and `pdp_status` properties return `ok`, `warning` (≤30 days), or `expired`.

**DriverScore** — daily composite driving score (0–100). Components: trip count, distance, speeding events, harsh acceleration events, idle minutes.

**InspectionLog** — pre/post-trip checklist submission. Checklist is stored as a JSON dict keyed by item code (tyres, lights, brakes, fuel, oil, windscreen, mirrors, fire_ext, first_aid, documents).

**VehicleDocument** — stores uploaded compliance files (COF, licence disc, insurance, roadworthy). `expiry_status` returns `ok`, `warning`, or `expired`.

**ServiceSchedule** — odometer-based service interval. `next_due_km` = `last_service_km + interval_km`.

**VideoChannel** — a logical camera on a vehicle (dashcam channel). Stores a live stream URL if available.

**VideoAsset** — a recorded clip. Can be stored locally under `MEDIA_ROOT` or on S3 (controlled by `VIDEO_STORAGE_BACKEND`). Auto-correlated to an Alert when the clip's timestamp falls within `VIDEO_ALERT_CORRELATION_WINDOW_MINUTES`.

---

## 6. GPS Ingest Pipeline

This is the most critical path in the system. Every position update from a tracker in the field travels through this pipeline.

### 6.1 Data flow

```
GPS Tracker (field)
      │  (proprietary binary/HTTP protocol)
      ▼
Traccar container
      │  (parses protocol, normalises position)
      │  POST /api/ingest/traccar/   Bearer <INGEST_API_TOKEN>
      ▼
tracking/ingest.py  ──  ingest_traccar()
      │
      ├── Resolve org from org_slug attribute (or TRACCAR_DEFAULT_ORG_SLUG)
      ├── get_or_create Vehicle by registration
      ├── Parse device_timestamp (ISO string or Unix ms from Traccar 6)
      ├── _get_or_create_trip()      ── open or continue a TrackedTrip
      ├── GPSPing.objects.create()   ── immutable position record
      ├── _update_trip_end()         ── update trip stats
      ├── check_geofences()          ── fire enter/exit events
      ├── _check_speeding_alert()    ── flag if speed > org limit
      ├── _check_idle_alert()        ── flag if stationary > 10 min
      ├── _resolve_fuel_level()      ── calibrate raw probe value
      │       └── _record_fuel()     ── save FuelReading + run detection
      ├── VehicleState upsert        ── update live map
      ├── _upsert_device()           ── register/update Device by IMEI
      ├── _maybe_geocode()           ── reverse geocode address (Nominatim, max 1/min)
      └── _push_to_myroutes()        ── fire-and-forget sync to myRoutes (if configured)
```

There is also `ingest_ping()` for direct HTTP POST from myRoutes (same logic, slightly different payload format).

### 6.2 Fuel level resolution

When a ping carries fuel data, `_resolve_fuel_level()` applies this priority chain:

1. `fuel_level_litres` in payload → use directly (CAN bus, already in litres)
2. `fuel_raw_value` + `TankCalibration` → piecewise linear interpolation via strapping table
3. `fuel_level_pct` + `TankCalibration` → treat percentage as raw input into strapping table
4. `fuel_level_pct` × `Vehicle.fuel_tank_capacity_litres` → legacy linear fallback

Traccar attribute names accepted: `fuel1` (litres), `fuel1Percent` (%), `fuel_raw_value`, `fuel_level_litres`, `fuel_level_pct`.

### 6.3 Ingest authentication

All ingest endpoints check for `Authorization: Bearer <INGEST_API_TOKEN>` or `?token=` query parameter. Requests without a valid token return 401.

---

## 7. Fuel Detection Engine

`fuel/detection.py` runs after every `FuelReading` is saved.

### 7.1 Probe health gate

Runs first. If the reading is suspect, normal detection is skipped:
- **Zero reading** after a non-empty previous reading → `PROBE_FAULT` event (likely disconnected)
- **Stuck probe**: same value for 5 consecutive readings while vehicle moving >10 km/h → `PROBE_FAULT`

### 7.2 SMA baseline

Instead of comparing against a single previous reading, the engine computes the 5-point Simple Moving Average of the last 5 readings as the baseline. This eliminates false alerts from single slosh spikes.

### 7.3 Bifurcated mean theft detection

For theft/drain classification, the last 8 readings are split into two groups of 4 (oldest and newest). If `mean(oldest_4) − mean(newest_4) > theft_threshold`, the drop is genuine and sustained rather than transient sloshing.

### 7.4 Refuel speed gate

A level rise is only classified as a refuel if none of the last 3 readings show speed above 5 km/h. This prevents fuel sloshing to the front of the tank during hard acceleration from registering as a false refuel.

### 7.5 Thresholds

All thresholds are per-organisation and configurable in the admin:

| Threshold | Default | Purpose |
|---|---|---|
| `fuel_refuel_threshold_litres` | 8 L | Minimum rise to classify as refuel |
| `fuel_theft_threshold_litres` | 5 L | Minimum drop to trigger detection |
| `fuel_theft_speed_max_kmh` | 5 km/h | Speed gate: below = theft, above = drain |

---

## 8. Probe Calibration

The Fuel Calibration tool generates a unique strapping table for every tank it measures. That table is stored in myTrack and used to convert raw probe output to accurate litres.

### 8.1 How to calibrate a newly fitted tank

1. Run the Fuel Calibration tool on the drained tank, filling in measured increments and recording (raw probe value, litres) at each step
2. Export the results as a CSV (two columns: `raw_value`, `litres`)
3. In myTrack: **Fuel → Vehicle → Probe Calibration**
4. Set Bottom Blind Area (L) and Top Blind Area (L)
5. Click **Upload & Import** and select the CSV
6. Verify the calibration curve chart looks correct
7. Click **Save**

### 8.2 Interpolation algorithm

Piecewise linear: for an incoming raw value, find the two adjacent calibration points that bracket it and linearly interpolate. Values below the lowest point are clamped to the minimum reading plus the bottom blind area. Values above the highest point are clamped to the maximum reading. Implemented in `fuel/calibration.py::interpolate()`.

---

## 9. URL Structure

| Prefix | App | Key routes |
|---|---|---|
| `/` | tracking | Live dashboard, trip list, trip detail |
| `/app/` | mobile | Dispatcher PWA (Home, Map, Trips, Assets, trip replay) |
| `/api/mobile/` | mobile | JSON API for the mobile app (session auth) |
| `/vehicles/` | vehicles | Vehicle list, detail, devices |
| `/fuel/` | fuel | Fleet fuel overview, vehicle history, events, calibration editor |
| `/drivers/` | drivers | Driver list, detail, scores |
| `/geofences/` | geofences | Geofence list, map editor, event history |
| `/intelligence/` | intelligence | Fleet cost, trip reports, alert reports, driver scoring |
| `/compliance/` | compliance | Inspection logs, vehicle documents, service schedules |
| `/video/` | video_telematics | Clip library, channel health |
| `/tenancy/` | tenancy | Org settings, user management, depot management |
| `/admin-panel/` | tenancy | Super-admin: org creation, seat management |
| `/track/<uuid>/` | tracking | Public delivery tracking page (no login required) |
| `/api/ingest/ping/` | tracking | Server-to-server GPS ingest from myRoutes |
| `/api/ingest/traccar/` | tracking | GPS ingest from Traccar |
| `/admin/` | Django admin | Full database admin |

---

## 10. Environment Variables Reference

Full list from `.env.example`:

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | Yes | Django cryptographic secret — change in production |
| `DJANGO_DEBUG` | Yes | Set `False` in production |
| `DJANGO_ALLOWED_HOSTS` | Yes | Comma-separated hostnames |
| `POSTGRES_DB` | Yes | Database name |
| `POSTGRES_USER` | Yes | Database username |
| `POSTGRES_PASSWORD` | Yes | Database password |
| `POSTGRES_HOST` | Yes | Database hostname (use `db` inside Docker) |
| `POSTGRES_PORT` | Yes | Default `5432` |
| `INGEST_API_TOKEN` | Yes | Shared secret for GPS ingest endpoints |
| `TRACCAR_DEFAULT_ORG_SLUG` | Yes | Fallback org when device doesn't send `org_slug` |
| `TRACCAR_PUBLIC_HOST` | Yes | Public IP/domain shown in device setup instructions |
| `SITE_URL` | Yes | Used to build delivery tracking links |
| `ACS_CONNECTION_STRING` | For email | Azure Communication Services connection string |
| `ACS_SENDER_EMAIL` | For email | Sender address for automated emails |
| `MYROUTES_SYNC_URL` | Optional | Sync endpoint for myRoutes integration |
| `MYROUTES_SYNC_TOKEN` | Optional | Bearer token for myRoutes sync |
| `VIDEO_STORAGE_BACKEND` | Optional | `local` (default) or `s3` |
| `VIDEO_S3_BUCKET` | If S3 | S3 bucket name |
| `VIDEO_S3_REGION` | If S3 | AWS region |
| `VIDEO_S3_ACCESS_KEY_ID` | If S3 | AWS access key |
| `VIDEO_S3_SECRET_ACCESS_KEY` | If S3 | AWS secret key |
| `VIDEO_CLIP_REQUEST_URL` | Optional | Vendor endpoint for proactive clip requests |
| `VIDEO_CLIP_REQUEST_TOKEN` | Optional | Auth token for clip request vendor |
| `STREAMAX_WEBHOOK_TOKEN` | Optional | Shared secret for Streamax camera push events |

---

## 11. Key Third-Party Integrations

### Traccar
Open-source GPS server that handles the hardware tracker protocols. myTrack does not implement any tracker protocols directly. Traccar decodes the binary payload from the device and forwards a normalised position (lat, lon, speed, attributes) via HTTP POST to `/api/ingest/traccar/`.

Configuration lives in `traccar/traccar.xml` (generated from `traccar.xml.tpl` at deploy time). The forward URL, token, and attribute forwarding are all set there.

### myRoutes
A separate Django application for delivery route management. myTrack receives GPS pings forwarded from myRoutes trips via `/api/ingest/ping/`, and pushes position updates back to myRoutes via `_push_to_myroutes()` (fire-and-forget in a background thread).

### Azure Communication Services
Used for outbound email (fuel theft alerts, probe fault alerts, drain alerts, excess consumption alerts). Configured via `ACS_CONNECTION_STRING` and `ACS_SENDER_EMAIL`. Falls back silently on failure — alerts are still stored in the database even if email fails.

### Nominatim (OpenStreetMap)
Used for reverse geocoding (`_maybe_geocode()`). Rate-limited to one request per minute per vehicle to avoid abuse. Address is stored in `VehicleState.last_address`.

### AWS S3 (optional)
Video clips can be stored on S3 instead of local disk. When `VIDEO_STORAGE_BACKEND=s3`, the system generates presigned PUT URLs for upload and presigned GET URLs for playback.

### Streamax cameras
Streamax AD Plus 2.0 cameras push events via webhook to `/video/streamax/webhook/`. The shared secret is validated against `STREAMAX_WEBHOOK_TOKEN`.

---

## 12. User Roles

| Role | Access |
|---|---|
| **Admin** | Full access to all vehicles, all depots, all settings, user management |
| **Dispatcher** | Access to their assigned depots only; can create delivery shares, acknowledge events |
| **Viewer** | Read-only across their assigned depots |

Superuser accounts (Django `is_superuser=True`) have access to the `/admin/` and `/admin-panel/` interfaces for managing organisations and creating the first admin user.

---

## 13. Common Operational Tasks

### Add a new organisation
1. Log in as superuser
2. Go to `/admin-panel/` → Create Organisation
3. Create the first Admin user for that org

### Add a new vehicle
1. Go to **Vehicles → Add Vehicle**
2. Set registration to match exactly what the tracker sends as `deviceName` in Traccar
3. Set fuel tank capacity if no calibration probe is fitted
4. Set expected fuel consumption if excess consumption alerts are needed

### Add a GPS tracker to a vehicle
1. Configure the tracker to send to Traccar on the appropriate port (e.g. port 5027 for Teltonika)
2. Set `deviceName` on the tracker to the vehicle registration
3. Set `org_slug` attribute or configure `TRACCAR_DEFAULT_ORG_SLUG`
4. The device self-registers in myTrack on first ping

### Fit a fuel probe and calibrate
1. Physically fit the probe and run the Fuel Calibration tool
2. Go to **Fuel → Vehicle → Probe Calibration**
3. Import the CSV from the calibration tool
4. Set blind areas and save

### Run a database migration after deployment
```bash
docker compose exec web python manage.py migrate
```

### View application logs
```bash
docker compose logs -f web
docker compose logs -f traccar
```

### Create a superuser
```bash
docker compose exec web python manage.py createsuperuser
```

### Back up the database
```bash
docker compose exec db pg_dump -U mytrack mytrack > backup_$(date +%Y%m%d).sql
```

---

## 14. Repository Structure

```
myTrack/
├── .github/workflows/deploy.yml   CI/CD — deploy on push to master
├── mytrack/
│   ├── config/                    Django settings, urls, wsgi
│   ├── tenancy/                   Orgs, depots, users
│   ├── vehicles/                  Vehicle registry and device management
│   ├── tracking/                  GPS ingest, trips, alerts, delivery shares
│   ├── fuel/                      Fuel readings, events, calibration
│   ├── drivers/                   Driver profiles and scoring
│   ├── geofences/                 Polygon geofences and events
│   ├── intelligence/              Dashboards and reports
│   ├── compliance/                Inspections, documents, service schedules
│   ├── notifications/             Email dispatch
│   ├── video_telematics/          Dashcam clip management
│   └── templates/                 All HTML templates (one folder per app)
├── traccar/
│   └── traccar.xml.tpl            Traccar config template (token injected at deploy)
├── Dockerfile                     Production container definition
├── docker-compose.yml             Local development environment
├── docker-compose.prod.yml        Production environment
├── requirements.txt               Python dependencies
├── manage.py                      Django management entry point
└── .env.example                   Environment variable reference
```

---

## 15. Mobile dispatcher PWA (iPhone)

Dispatchers and viewers are redirected to `/app/` after login (admins still land on `/` unless `?desktop=1` is used).

**Install on iPhone 16 (or later):**

1. Open **Safari** and sign in at the production URL (HTTPS required).
2. Navigate to `/app/`.
3. Tap **Share** → **Add to Home Screen**.
4. Launch myTrack from the home screen icon for standalone (full-screen) mode.

**Notes:**

- Live positions use SSE (`/live/stream/`). iOS may pause updates when the app is backgrounded; bring the app to the foreground to refresh.
- Depot scope matches the desktop dashboard: dispatchers only see vehicles for depots they are granted; use **Menu → Depot** to switch.
- Trip **Personal/Business** classification is stored on `TrackedTrip.classification`; start/end address labels are filled when a trip closes.
- **Share location** creates a `DeliveryShare` link (`/track/<uuid>/`) suitable for the iOS share sheet.
- UI uses the MhareReach palette (cyan `#00C8FF`, purple `#8A2BE2`, periwinkle `#C5CAE9`) and the shared `truck` icon from `static/js/icons.js`.

After deploying code that includes migration `tracking.0014_trackedtrip_classification_labels`, run:

```bash
docker compose exec web python manage.py migrate
```

---

## 16. Known Gaps and Future Work

The following items have been identified as future improvements (not yet built):

| Item | Description |
|---|---|
| Auto-run migrations on deploy | The CI/CD pipeline restarts the web container but does not automatically run `migrate` |
| Configurable device mapper | Currently tracker attribute names (`fuel1`, `fuel1Percent`, etc.) are hardcoded in `ingest.py`. A per-device-model mapper UI would allow new hardware to be supported without code changes |
| Cross-sensor validation | Wialon-style validator: ignore fuel reading if battery voltage or power supply sensor is faulty |
| Traccar computed attributes for fuel deltas | Traccar can compute `lastFuel1` natively, which could replace some detection logic |
| Kafka / async ingestion | At very high vehicle counts (thousands), a message queue between Traccar and myTrack would prevent dropped pings under traffic spikes |
| Database backups | No automated backup schedule is configured; this must be set up on the production server |
| Device battery / ignition attrs | Mobile asset sheet shows derived ignition (from speed) and placeholder battery until Traccar attributes are stored on `VehicleState` |

---

*End of handover document.*
