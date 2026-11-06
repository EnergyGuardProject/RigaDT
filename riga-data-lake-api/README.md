# Riga Data Lake API

A small FastAPI service that exposes Riga datasets stored in the EnergyGuard data lake (PostgreSQL) over HTTP, so that solution providers can integrate the building data into their own applications and analytics pipelines.

Interactive documentation (Swagger UI) is served at `/docs` and the OpenAPI schema at `/openapi.json`.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health/info message |
| GET | `/georiga/building-monthly-heat-series` | Monthly per-building heat consumption (GeoRiga REA) |
| GET | `/georiga/addresses` | Address points |
| GET | `/georiga/existing-buildings` | Existing building footprints |
| GET | `/georiga/demolished-buildings` | Demolished building footprints |
| GET | `/georiga/streets` | Street centre lines |
| GET | `/georiga/building-energy-efficiency-indicators` | Per-building energy efficiency indicators (energy class, heat use, renovation)* |
| GET | `/georiga/renovated-buildings-energy-efficiency` | Renovated buildings: measures, financing, planned/achieved savings* |
| GET | `/georiga/degraded-buildings` | Environment-degrading buildings* |
| GET | `/georiga/suburbs` | Suburb boundaries |
| GET | `/georiga/city-boundary` | City boundary |
| GET | `/georiga/heat-supply-zones` | Territorial zones for heat supply choice |
| GET | `/georiga/noise-2021-day` | Noise map 2021, day |
| GET | `/georiga/noise-2021-evening` | Noise map 2021, evening |
| GET | `/georiga/noise-2021-night` | Noise map 2021, night |
| GET | `/georiga/noise-2021-average` | Noise map 2021, day-evening-night average |
| GET | `/cadastre/buildings` | Cadastral building register* |
| GET | `/cadastre/building-amounts` | Building amounts (areas, volumes)* |
| GET | `/cadastre/building-elements` | Building elements* |
| GET | `/cadastre/building-element-materials` | Element materials* |
| GET | `/cadastre/building-improvements` | Building improvements* |
| GET | `/cadastre/building-parcels` | Building-parcel links* |
| GET | `/cadastre/building-types` | Building kind classification* |
| GET | `/cadastre/building-footprints` | Cadastral building geometries (`code` = cadastre number)* |
| GET | `/cadastre/parcels` | Cadastral parcel geometries (`code` = parcel number)* |
| GET | `/cadastre/cadastral-groups` | Cadastral group geometries |

### Dataset endpoints (`/georiga/*` and `/cadastre/*`)

One endpoint per table of the `gis` and `cadastre` schemas. They all return `{ "total", "limit", "offset", "data": [...] }` ordered by primary key.

| Query parameter | Applies to | Description |
|-----------------|-----------|-------------|
| `limit` (1–1000, default 100), `offset` | all | Pagination |
| `include_geometry` (default `true`) | datasets with geometry | Adds a `geometry` field (GeoJSON, WGS84/EPSG:4326; stored as LKS-92/EPSG:3059). Use `false` for much smaller responses |
| `cadastre_number` | endpoints marked `*` | Exact match on the dataset's cadastre column (404 if nothing matches) |

Column names are those of the source tables (mostly Latvian). Full details are in `/docs`.

Geometry can be large (about 15 KB per row for the noise maps, 47 KB for the city boundary), so for attribute-only use pass `include_geometry=false` or a small `limit`.

In `/docs` the endpoints are grouped by theme: Heat consumption, Buildings (GeoRiga), Energy efficiency, Noise 2021, Addresses & streets, Administrative boundaries, Cadastre - buildings, and Cadastre - land.

### `GET /georiga/building-monthly-heat-series`

Source: GeoRiga REA MapServer (`georiga.lv/server/rest/services/REA/MapServer`), mirrored in the data lake from TEF6_REA. Only heating sensors are returned, identified by a 14-digit sensor ID, which is the building's cadastre number.

| Query parameter | Type | Default | Description |
|-----------------|------|---------|-------------|
| `limit` | int (1–1000) | 100 | Page size |
| `offset` | int (≥ 0) | 0 | Rows to skip |
| `cadastre_number` | string | – | Return the full series of one building. When set, `limit` and `offset` are ignored |

Rows are ordered by `datetime`. Each row has:

| Field | Description |
|-------|-------------|
| `datetime` | Reading date |
| `sensor_id` | 14-digit cadastre number of the building |
| `building_address` | Sensor name, i.e. the building address |
| `f_value` | Measured heat consumption value |

**Paged response**

```json
{ "total": 12345, "limit": 100, "offset": 0, "data": [ { "datetime": "...", "sensor_id": "01001130039002", "building_address": "...", "f_value": 0.0 } ] }
```

**Single-building response** (`?cadastre_number=01001130039002`)

```json
{ "cadastre_number": "01001130039002", "count": 96, "data": [ ... ] }
```

**Errors**

| Status | Meaning |
|--------|---------|
| 404 | No heating data for the given cadastre number |
| 422 | Invalid query parameter (e.g. `limit` out of range) |
| 502 | Database connection failed |

## Configuration

Settings are read from environment variables, or from a `.env` file. Copy `.env.example` to `.env` and fill it in.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_HOST` | yes | – | PostgreSQL host |
| `DB_PORT` | no | `5432` | PostgreSQL port |
| `DB_USER` | yes | – | Database user |
| `DB_PASSWORD` | yes | – | Database password |
| `DB_NAME` | yes | – | Database name |
| `DB_SSLMODE` | no | `require` | psycopg2 `sslmode` |

The app refuses to start if a required variable is missing. `.env` is git-ignored and must never be committed.

## Run with Docker

```bash
cp .env.example .env   # then edit
docker compose up -d --build
```

The container listens on port 8001 and is published on host port **9007**:

```bash
curl "http://localhost:9007/georiga/building-monthly-heat-series?limit=5"
curl "http://localhost:9007/georiga/building-monthly-heat-series?cadastre_number=01001130039002"
```

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit
uvicorn app:app --host 0.0.0.0 --port 8001
```

## Project layout

```
riga-data-lake-api/
├── app.py               # FastAPI app, queries and endpoints
├── requirements.txt     # Python dependencies
├── Dockerfile           # python:3.12-slim image, runs uvicorn on 8001
├── docker-compose.yml   # service definition (host port 9007 → 8001)
├── .env.example         # template for database settings
└── .dockerignore / .gitignore
```

## Notes

- The database is only read, never written.
- Schemas queried: `public` (`d_sensor`, `d_sensor_type`, `f_tsdata`, `d_calendar`), `gis` and `cadastre`.
- Other sensor types are defined in `d_sensor_type`, but the lake holds data only for the heat series, so there are no endpoints for them.
