# Road speed data (OpenStreetMap → PostGIS)

myTrack resolves **posted speed limits** from the `tracking_roadsegment` table (created empty by Django migration `tracking.0009`). Populate it from a Geofabrik extract with **osm2pgsql** in flex mode.

## Prerequisites

- PostgreSQL **with PostGIS** (the repo `docker-compose.yml` uses the `postgis/postgis` image).
- [osm2pgsql](https://osm2pgsql.org/) 1.9+ with flex, or the `iboates/osm2pgsql` Docker image.

## 1. Download South Africa extract

From [Geofabrik South Africa](https://download.geofabrik.de/africa/south-africa-latest.osm.pbf).

## 2. Apply Django migrations

Ensure `tracking_roadsegment` exists (empty) and PostGIS is enabled:

```bash
python manage.py migrate
```

## 3. Import OSM ways

The flex style [`roads.lua`](roads.lua) writes into `tracking_roadsegment` with the same columns as the migration:

| Column      | Type                      |
|------------|---------------------------|
| osm_way_id | bigint PRIMARY KEY        |
| highway    | varchar(64)               |
| maxspeed   | text (raw OSM tag)        |
| geom       | geometry(LineString, 4326)|

**Import into the existing empty table** using `--append` (not `--create`, which would conflict with Django-owned DDL):

```bash
docker run --rm -it --network host \
  -v /path/to/south-africa-latest.osm.pbf:/data.osm.pbf:ro \
  -v "$(pwd)/scripts/road_osm/roads.lua:/roads.lua:ro" \
  iboates/osm2pgsql:latest \
  osm2pgsql --append --database mytrack --username mytrack --host localhost --port 5433 \
    --output=flex --style=/roads.lua /data.osm.pbf
```

If you previously loaded data and need a full refresh:

```sql
TRUNCATE tracking_roadsegment;
```

Then run the same `osm2pgsql --append` command again.

**Alternative (recreate table via osm2pgsql only):** `DROP TABLE tracking_roadsegment CASCADE;` then `osm2pgsql --create ...` with this flex file, then `python manage.py migrate` is **not** required again — but the next `migrate` noop is fine. Prefer **truncate + append** to stay aligned with Django’s table definition.

## 4. Refresh cadence

Re-download the PBF periodically (e.g. monthly) and repeat truncate + append.

## 5. Runtime behaviour

- Enable **Road speed limits** on the organisation (staff **Applications → org → Settings**).
- Ingest order: **Traccar `speedLimit`-style attributes** → **cell cache** → **nearest OSM way** (~85 m) → org **fallback km/h**.
- Tag parsing lives in `mytrack.tracking.road_maxspeed` (including `ZA:urban` / `ZA:rural` / `ZA:motorway`).
