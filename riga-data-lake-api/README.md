# Riga Data Lake API

A small FastAPI service that exposes Riga datasets stored in the EnergyGuard data lake (PostgreSQL) over HTTP, so that solution providers can integrate the building data into their own applications and analytics pipelines.

Interactive documentation (Swagger UI) is served at `/docs` and the OpenAPI schema at `/openapi.json`.

## Authentication

All data endpoints require a Keycloak access token from the EnergyGuard realm (any authenticated realm user is allowed). Send it as a bearer token:

```bash
curl -H "Authorization: Bearer $TOKEN" "https://dashboard.energy-guard.eu/riga-data-lake-api/georiga/streets?limit=5"
```

Requests without a valid token get `401` (with a `WWW-Authenticate: Bearer` header); if Keycloak's signing keys cannot be fetched the API answers `503`. `/docs` and `/openapi.json` are public, and the **Authorize** button in `/docs` signs you in through Keycloak (needs `KC_DOCS_CLIENT_ID`, see below).

Tokens are verified locally against the realm's public keys (RS256, issuer and expiry checked), so the API holds no Keycloak secret. See `auth.py`.

**Getting a token** (for scripts): request one from `<KC_ISSUER_URL>/protocol/openid-connect/token` with your EnergyGuard username and password, using the `riga-data-lake-api` client (password grant). A step-by-step example is in [Testing the API](#testing-the-api). For an unattended application, ask the realm admin for a service-account client instead of using a personal password.

**Swagger sign-in:** clicking **Authorize** in `/docs` goes straight to the Keycloak login (no intermediate dialog) and the button then reads **Authorized**; click it again to log out. The token is held only in the page, so a reload signs you out, and the page signs itself out when the token expires. This is done by a small script in `docs_ui.py`; without `KC_DOCS_CLIENT_ID` Swagger's stock dialog is shown instead.

**Swagger client setup:** create a *public* Keycloak client with standard flow and PKCE (S256), set its valid redirect URI to `<public API URL>/docs/oauth2-redirect` (e.g. `https://dashboard.energy-guard.eu/riga-data-lake-api/docs/oauth2-redirect`), and put its client ID in `KC_DOCS_CLIENT_ID`.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health/info message |
| GET | `/whoami` | The signed-in user and token expiry (401 if not signed in) |
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

## Run with Docker

```bash
cp .env.example .env   # then edit
docker compose up -d --build
```

The container listens on port 8001 and is published on host port **9007**, bound to `127.0.0.1` only (reach it from your machine with an SSH tunnel: `ssh -L 9007:127.0.0.1:9007 user@server`). In production it sits behind Nginx Proxy Manager at `https://dashboard.energy-guard.eu/riga-data-lake-api/` (the compose file runs uvicorn with `--root-path /riga-data-lake-api` and joins the `nginxproxy_energyguard_net` network).

Requests need a token (see [Testing the API](#testing-the-api)):

```bash
curl -H "Authorization: Bearer $TOKEN" "http://localhost:9007/georiga/building-monthly-heat-series?limit=5"
curl -H "Authorization: Bearer $TOKEN" "http://localhost:9007/georiga/building-monthly-heat-series?cadastre_number=01001130039002"
```

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit
uvicorn app:app --host 0.0.0.0 --port 8001
```

## Testing the API

Three ways, from quickest to most thorough. `BASE` below is `https://dashboard.energy-guard.eu/riga-data-lake-api` (production), or `http://127.0.0.1:9007` on the server, or `http://localhost:8011` for a local run (see the redirect-URI note).

### 1. In the browser (Swagger UI)

1. Open `BASE/docs`. The **Authorize** button is red and the padlocks are open.
2. Click **Authorize**. A Keycloak window opens (allow popups for the site if nothing happens).
3. Sign in with your EnergyGuard username and password.
4. The window closes, the button turns green and reads **Authorized**, and the padlocks close.
5. Open `GET /whoami` → **Try it out** → **Execute**. A `200` with your name means you are signed in.
6. Try any data endpoint the same way, e.g. `GET /georiga/suburbs` with `limit=1` and `include_geometry=false`.
7. Click **Authorized** → **Logout**, then execute again: you should get `401 Missing bearer token`.

A closed padlock means "secured, and your token is attached"; an open one means you have not authorized yet. Reloading the page signs you out, and the page signs you out by itself when the token expires.

**Redirect-URI note:** Keycloak only accepts the redirect addresses registered on the client. For a local run use exactly `http://localhost:8011/docs/oauth2-redirect`, i.e. port **8011** and the host name `localhost` (not `127.0.0.1`), otherwise Keycloak shows `Invalid parameter: redirect_uri`.

### 2. With curl

Type the password at a prompt so it never lands in your shell history or on screen, then fetch a token:

```bash
read -s -p "EnergyGuard password: " PW; echo

TOKEN=$(curl -s -X POST https://keycloak.toolbox.epu.ntua.gr/realms/EnergyGuard/protocol/openid-connect/token \
  -d grant_type=password -d client_id=riga-data-lake-api \
  --data-urlencode "username=YOUR_USERNAME" \
  --data-urlencode "password=$PW" | jq -r .access_token); unset PW
echo "token length: ${#TOKEN}"     # about 1000; 4 means "null", i.e. the login failed
```

Run the `read` line on its own first (when pasting, `read -s` would swallow the next line). The client needs *Direct access grants* enabled. Then call the API:

```bash
BASE=https://dashboard.energy-guard.eu/riga-data-lake-api   # or http://127.0.0.1:9007 on the server
curl -H "Authorization: Bearer $TOKEN" "$BASE/whoami"
curl -H "Authorization: Bearer $TOKEN" "$BASE/georiga/suburbs?limit=1&include_geometry=false"
curl -H "Authorization: Bearer $TOKEN" "$BASE/cadastre/buildings?cadastre_number=01000010003001"
```

Without the header you should get `401`:

```bash
curl -i "$BASE/georiga/suburbs?limit=1"
```

Access tokens are short-lived (minutes). After `401 Token expired`, fetch a new one.

### 3. With the check script

`scripts/check_login.py` does the login and all of the checks above in one go (it uses only the Python standard library):

```bash
read -s -p "EnergyGuard password: " KC_PASSWORD; echo; export KC_PASSWORD
export KC_USERNAME=YOUR_USERNAME
python3 scripts/check_login.py
# on the server, against the local container:
API_URL=http://127.0.0.1:9007 python3 scripts/check_login.py
```

It prints PASS/FAIL per check (login, `/whoami`, two data endpoints, `401` without and with a bad token, public `/docs`) and exits non-zero if anything failed. It never prints the password or the token. `KC_ISSUER_URL`, `KC_CLIENT_ID` and `API_URL` can be overridden.

### Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `Invalid parameter: redirect_uri` on Keycloak | Page opened on a host/port that is not registered on the client (see the note above) |
| `Client not found` | `KC_DOCS_CLIENT_ID` / `client_id` does not match the Keycloak client |
| Nothing opens on **Authorize** | Popup blocked: allow popups for the site |
| Token request answers `invalid_grant` | Wrong username/password, or the account needs an action (e.g. password change) |
| Token request answers `unauthorized_client` | *Direct access grants* is off on the client |
| `401 Invalid token` | Token from another realm/host (issuer must equal `KC_ISSUER_URL`), or `$TOKEN` is empty / `null` |
| `401 Token expired` | Fetch a new token / click **Authorize** again |
| `503 Authentication service unavailable` | The API cannot fetch Keycloak's signing keys: check the server's network access to Keycloak |
| `502 Database connection failed` | Database unreachable: check `DB_*` settings |

## Project layout

```
riga-data-lake-api/
├── app.py               # FastAPI app, queries and endpoints
├── auth.py              # Keycloak bearer-token verification
├── docs_ui.py           # /docs page with one-click Keycloak sign-in
├── scripts/check_login.py  # end-to-end login and access check
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
