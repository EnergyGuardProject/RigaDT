
import logging
import os
from datetime import datetime, timezone

import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query

from auth import KC_DOCS_CLIENT_ID, require_user
from docs_ui import install_docs

load_dotenv()

logger = logging.getLogger(__name__)


def _required_setting(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

TAGS_METADATA = [
    {"name": "Authentication", "description": "Check who you are signed in as."},
    {"name": "Heat consumption", "description": "Monthly per-building heat consumption time series (GeoRiga REA)."},
    {"name": "Buildings (GeoRiga)", "description": "Existing, demolished and environment-degrading building footprints."},
    {"name": "Energy efficiency", "description": "Building energy efficiency indicators, renovated buildings and heat supply zones."},
    {"name": "Noise 2021", "description": "Strategic noise map 2021 (day, evening, night, average)."},
    {"name": "Addresses & streets", "description": "Address points and street centre lines."},
    {"name": "Administrative boundaries", "description": "Riga city boundary and suburbs."},
    {"name": "Cadastre - buildings", "description": "Cadastral building register and its attributes (amounts, elements, materials, improvements, types)."},
    {"name": "Cadastre - land", "description": "Cadastral parcels, groups, building footprints and building-parcel links."},
]

app = FastAPI(
    # Every route requires a Keycloak token; /docs and /openapi.json stay public.
    dependencies=[Depends(require_user)],
    docs_url=None,  # /docs is served by docs_ui.install_docs() below
    swagger_ui_oauth2_redirect_url=None,
    openapi_tags=TAGS_METADATA,
    title="Riga Data Lake API",
    description=(
        "Data endpoints for the Riga TEF pilot, one per source dataset from the "
        "GeoRiga / data.gov.lv open-data catalogue and the EnergyGuard consortium "
        "(building audits, heat consumption, meteorology, air quality, energy "
        "certificates, spatial/cadastral data, and more)."
    ),
)

install_docs(
    app,
    init_oauth=(
        {"clientId": KC_DOCS_CLIENT_ID, "usePkceWithAuthorizationCodeGrant": True}
        if KC_DOCS_CLIENT_ID
        else None
    ),
)

DB_HOST = _required_setting("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = _required_setting("DB_USER")
DB_PASSWORD = _required_setting("DB_PASSWORD")
DB_NAME = _required_setting("DB_NAME")
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")

BUILDINGS_COLUMNS = ["datetime", "sensor_id", "building_address", "f_value"]

HEATING_SENSOR_FILTER = "ds.sensor_id ~ '^[0-9]{14}$'"

BUILDINGS_QUERY = f"""
    SELECT dc.datetime, ds.sensor_id, ds.name, f.f_value
    FROM public.d_sensor ds
    JOIN public.d_sensor_type dst ON ds.type_id = dst.sensor_type_id
    LEFT JOIN public.f_tsdata f ON ds.sensor_id = f.sensor_id
    LEFT JOIN public.d_calendar dc ON f.calendar_id = dc.calendar_id
    WHERE {HEATING_SENSOR_FILTER}
    ORDER BY dc.datetime
    LIMIT %s OFFSET %s
"""

BUILDINGS_BY_CADASTRE_QUERY = f"""
    SELECT dc.datetime, ds.sensor_id, ds.name, f.f_value
    FROM public.d_sensor ds
    JOIN public.d_sensor_type dst ON ds.type_id = dst.sensor_type_id
    LEFT JOIN public.f_tsdata f ON ds.sensor_id = f.sensor_id
    LEFT JOIN public.d_calendar dc ON f.calendar_id = dc.calendar_id
    WHERE {HEATING_SENSOR_FILTER} AND ds.sensor_id = %s
    ORDER BY dc.datetime
"""

COUNT_QUERY = f"""
    SELECT COUNT(*)
    FROM public.d_sensor ds
    LEFT JOIN public.f_tsdata f ON ds.sensor_id = f.sensor_id
    WHERE {HEATING_SENSOR_FILTER}
"""


def _connect():
    try:
        return psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname=DB_NAME,
            sslmode=DB_SSLMODE,
            connect_timeout=10,
        )
    except psycopg2.OperationalError:
        logger.exception("Database connection failed")
        raise HTTPException(status_code=502, detail="Database connection failed")


# ---------------------------------------------------------------------------
# Generic dataset endpoints (one per table in the `gis` and `cadastre` schemas)
#
# Table and column names come only from this registry (never from user input),
# and are composed with psycopg2.sql so identifiers are always quoted safely.
# Geometries are stored in LKS-92 (EPSG:3059) and returned as GeoJSON in WGS84.
# ---------------------------------------------------------------------------

DATASETS = [
    # --- gis schema: GeoRiga open data -------------------------------------
    dict(
        path="/georiga/addresses", tag="Addresses & streets", schema="gis", table="adreses", order="gid",
        title="Riga Addresses",
        description="Address points of Riga (address, street, house number).",
        columns=["gid", "adrese", "iela", "numurs", "rotation"], geom=True,
    ),
    dict(
        path="/georiga/existing-buildings", tag="Buildings (GeoRiga)", schema="gis", table="esosas_buves", order="gid",
        title="Existing Buildings (GeoRiga)",
        description="Footprints of existing buildings in Riga with registration info, type and number of floors.",
        columns=["gid", "name", "reg_info", "reg_datums", "piezimes", "tips", "buves_teks", "stavu_skai"], geom=True,
    ),
    dict(
        path="/georiga/demolished-buildings", tag="Buildings (GeoRiga)", schema="gis", table="nojauktas_buves", order="gid",
        title="Demolished Buildings (GeoRiga)",
        description="Footprints of buildings that have been demolished, with deletion date and info.",
        columns=["gid", "reg_info", "reg_datums", "piezimes", "tips", "buves_teks", "stavu_skai", "dzests_dat", "dzests_inf"], geom=True,
    ),
    dict(
        path="/georiga/streets", tag="Addresses & streets", schema="gis", table="ielas", order="gid",
        title="Riga Streets",
        description="Street centre lines of Riga with name and naming decision info.",
        columns=["gid", "nosaukums", "lemuma_dat", "lemuma_nr", "lemuma_nos", "darbiba", "piezimes"], geom=True,
    ),
    dict(
        path="/georiga/building-energy-efficiency-indicators", tag="Energy efficiency", schema="gis",
        table="majas_energoefektivitates_raditaji", order="gid",
        title="Building Energy Efficiency Indicators",
        description="Per-building energy efficiency indicators: floor area, average and certified heat consumption, energy class, renovation status, neighbourhood.",
        columns=["gid", "id", "adrese", "cadastrena", "ekspl_gads", "lietd_plat", "vid_ip_apk",
                 "ip_paterin", "enef_klase", "ipatn_silt", "filtrs", "renovacija", "apkaime"],
        geom=True, filter_col="cadastrena",
    ),
    dict(
        path="/georiga/renovated-buildings-energy-efficiency", tag="Energy efficiency", schema="gis",
        table="renoveto_eku_energoefektiviate", order="gid",
        title="Renovated Buildings Energy Efficiency",
        description="Renovated buildings with financing, renovation measures (walls, windows, roof, heating, ventilation...), planned and achieved heat savings.",
        columns=["gid", "btrim", "cadastrena", "ekspl_gads", "kopeja_pla", "renovacija", "finansejum",
                 "kopejas_re", "apstiprin_", "renov_izma", "paterins_p", "paterins_1", "paterins_2",
                 "paterins_3", "planotais_", "sasniegtai", "enef_klase", "arsienu_si", "logu_nomai",
                 "ardurvju_n", "lodziju_ie", "cokola_sil", "pagraba_si", "jumta_silt", "ventilacij",
                 "ventilac_1", "divcaurulu", "apkures_si", "apkures_in", "karstauden", "apkaime"],
        geom=True, filter_col="cadastrena",
    ),
    dict(
        path="/georiga/degraded-buildings", tag="Buildings (GeoRiga)", schema="gis", table="vidi_degradejosas_buves", order="gid",
        title="Environment-Degrading Buildings",
        description="Buildings that degrade the urban environment, with status, ownership and council decision.",
        columns=["gid", "id", "adrese", "koordinate", "statuss", "regions", "piederiba", "piezimes",
                 "rd_lemums", "cadastrena", "klasifikac"],
        geom=True, filter_col="cadastrena",
    ),
    dict(
        path="/georiga/suburbs", tag="Administrative boundaries", schema="gis", table="rigas_priekspilsetas", order="gid",
        title="Riga Suburbs",
        description="Riga suburb (priekspilseta) boundaries.",
        columns=["gid", "area", "atk", "nosaukums", "izpilddire"], geom=True,
    ),
    dict(
        path="/georiga/city-boundary", tag="Administrative boundaries", schema="gis", table="rigas_robeza", order="gid",
        title="Riga City Boundary",
        description="Administrative boundary of Riga.",
        columns=["gid"], geom=True,
    ),
    dict(
        path="/georiga/heat-supply-zones", tag="Energy efficiency", schema="gis",
        table="teritorialas_zonas_siltumapgades_izvelei", order="gid",
        title="Territorial Zones for Heat Supply Choice",
        description="Territorial zones defining heat supply options.",
        columns=["gid", "zona"], geom=True,
    ),
    dict(
        path="/georiga/noise-2021-day", tag="Noise 2021", schema="gis", table="noise_2021_diena", order="gid",
        title="Noise Map 2021 - Day",
        description="Strategic noise map 2021, day period. `db` is the noise band in dB.",
        columns=["gid", "db"], geom=True,
    ),
    dict(
        path="/georiga/noise-2021-evening", tag="Noise 2021", schema="gis", table="noise_2021_vakars", order="gid",
        title="Noise Map 2021 - Evening",
        description="Strategic noise map 2021, evening period. `db` is the noise band in dB.",
        columns=["gid", "db"], geom=True,
    ),
    dict(
        path="/georiga/noise-2021-night", tag="Noise 2021", schema="gis", table="noise_2021_nakts", order="gid",
        title="Noise Map 2021 - Night",
        description="Strategic noise map 2021, night period. `db` is the noise band in dB.",
        columns=["gid", "db"], geom=True,
    ),
    dict(
        path="/georiga/noise-2021-average", tag="Noise 2021", schema="gis", table="noise_2021_videjais", order="gid",
        title="Noise Map 2021 - Day-Evening-Night Average",
        description="Strategic noise map 2021, day-evening-night average indicator. `db` is the noise band in dB.",
        columns=["gid", "db"], geom=True,
    ),
    # --- cadastre schema: State Land Service (VZD) building cadastre -------
    dict(
        path="/cadastre/buildings", tag="Cadastre - buildings", schema="cadastre", table="building", order="building_cadastre_nr",
        title="Cadastre Buildings",
        description="Cadastral building register: use, areas, floors, construction year, parcel, wall material, status.",
        columns=["building_cadastre_nr", "varis_code", "building_name", "use_kind_id", "use_kind_name",
                 "building_area", "building_constr_area", "ground_floors", "underground_floors",
                 "exploit_year", "parcel_cadastre_nr", "material_kind_id", "material_kind_name",
                 "preg_count", "acception_years", "deprecation", "depreciation_date", "survey_date",
                 "not_for_land_book", "prereg", "not_exist", "engineering_structure_type",
                 "related_object_type"],
        filter_col="building_cadastre_nr",
    ),
    dict(
        path="/cadastre/building-amounts", tag="Cadastre - buildings", schema="cadastre", table="building_amount", order="id",
        title="Cadastre Building Amounts",
        description="Quantitative building indicators (areas, volumes, counts) per building.",
        columns=["id", "building_cadastre_nr", "amount_kind_name", "amount_quantity", "measure_kind_name",
                 "building_kind_id", "building_kind_name"],
        filter_col="building_cadastre_nr",
    ),
    dict(
        path="/cadastre/building-elements", tag="Cadastre - buildings", schema="cadastre", table="building_element", order="id",
        title="Cadastre Building Elements",
        description="Building structural elements and their exploitation year.",
        columns=["id", "building_cadastre_nr", "element_name", "exploit_year"],
        filter_col="building_cadastre_nr",
    ),
    dict(
        path="/cadastre/building-element-materials", tag="Cadastre - buildings", schema="cadastre", table="building_element_material", order="id",
        title="Cadastre Building Element Materials",
        description="Materials of the structural elements of each building.",
        columns=["id", "building_cadastre_nr", "element_name", "element_exploit_year", "material_kind_id", "material_kind_name"],
        filter_col="building_cadastre_nr",
    ),
    dict(
        path="/cadastre/building-improvements", tag="Cadastre - buildings", schema="cadastre", table="building_improvement", order="id",
        title="Cadastre Building Improvements",
        description="Improvements (renovations, upgrades) recorded per building.",
        columns=["id", "building_cadastre_nr", "improvement_date", "improvement_type_name"],
        filter_col="building_cadastre_nr",
    ),
    dict(
        path="/cadastre/building-parcels", tag="Cadastre - land", schema="cadastre", table="building_parcel", order="id",
        title="Cadastre Building-Parcel Links",
        description="Links between buildings and land parcels.",
        columns=["id", "building_cadastre_nr", "parcel_cadastre_nr"],
        filter_col="building_cadastre_nr",
    ),
    dict(
        path="/cadastre/building-types", tag="Cadastre - buildings", schema="cadastre", table="building_type", order="id",
        title="Cadastre Building Types",
        description="Building kind classification per building.",
        columns=["id", "building_cadastre_nr", "building_kind_id", "building_kind_name"],
        filter_col="building_cadastre_nr",
    ),
    dict(
        path="/cadastre/building-footprints", tag="Cadastre - land", schema="cadastre", table="kkbuilding", order="gid",
        title="Cadastre Building Footprints",
        description="Cadastral map building geometries. `code` is the building cadastre number.",
        columns=["gid", "code", "objectcode", "parcelcode", "area_scale", "group_code"],
        geom=True, filter_col="code",
    ),
    dict(
        path="/cadastre/parcels", tag="Cadastre - land", schema="cadastre", table="kkparcel", order="gid",
        title="Cadastre Parcels",
        description="Cadastral map land parcel geometries. `code` is the parcel cadastre number.",
        columns=["gid", "code", "geom_act_d", "objectcode", "area_scale", "group_code"],
        geom=True, filter_col="code",
    ),
    dict(
        path="/cadastre/cadastral-groups", tag="Cadastre - land", schema="cadastre", table="kkcadastralgroup", order="gid",
        title="Cadastral Groups",
        description="Cadastral group (district) geometries.",
        columns=["gid", "code", "area_scale", "objectcode"], geom=True,
    ),
]


def _fetch_dataset_page(ds, limit, offset, include_geometry, filter_value):
    table = sql.Identifier(ds["schema"], ds["table"])
    select = [sql.Identifier(c) for c in ds["columns"]]
    if ds.get("geom") and include_geometry:
        select.append(sql.SQL("ST_AsGeoJSON(ST_Transform(geom, 4326), 6)::json AS geometry"))
    where = sql.SQL("")
    params = []
    if filter_value is not None:
        where = sql.SQL(" WHERE {} = %s").format(sql.Identifier(ds["filter_col"]))
        params.append(filter_value)

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(sql.SQL("SELECT COUNT(*) FROM {}{}").format(table, where), params)
        total = cur.fetchone()[0]
        cur.execute(
            sql.SQL("SELECT {} FROM {}{} ORDER BY {} LIMIT %s OFFSET %s").format(
                sql.SQL(", ").join(select), table, where, sql.Identifier(ds["order"])
            ),
            params + [limit, offset],
        )
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, row)) for row in cur.fetchall()]
        cur.close()
    finally:
        conn.close()
    return total, rows


def _register_dataset(ds):
    has_geom = ds.get("geom", False)
    filter_col = ds.get("filter_col")

    def handler(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        include_geometry: bool = Query(
            True, description="Include the GeoJSON geometry (WGS84). Set to false for a much smaller payload."
        ) if has_geom else False,
        cadastre_number: str = Query(
            None, description=f"Exact match on `{filter_col}`."
        ) if filter_col else None,
    ):
        filter_value = cadastre_number if filter_col else None
        total, rows = _fetch_dataset_page(ds, limit, offset, include_geometry, filter_value)
        if filter_value is not None and not rows and offset == 0:
            raise HTTPException(status_code=404, detail="No records found for this cadastre number")
        return {"total": total, "limit": limit, "offset": offset, "data": rows}

    handler.__name__ = ds["path"].strip("/").replace("/", "_").replace("-", "_")
    app.get(ds["path"], tags=[ds["tag"]], summary=ds["title"], description=(
        f"{ds['description']} Source table: `{ds['schema']}.{ds['table']}`."
    ))(handler)


for _ds in DATASETS:
    _register_dataset(_ds)


@app.get(
    "/whoami",
    tags=["Authentication"],
    summary="Who am I",
    description=(
        "Returns the EnergyGuard user the bearer token belongs to and when it "
        "expires. Use it to check that you are signed in: it answers 401 if you "
        "are not."
    ),
)
def whoami(claims: dict = Depends(require_user)):
    if claims is None:  # AUTH_DISABLED (local development)
        return {"authenticated": False, "auth_disabled": True}
    return {
        "authenticated": True,
        "username": claims.get("preferred_username"),
        "name": claims.get("name"),
        "email": claims.get("email"),
        "subject": claims.get("sub"),
        "expires_at": datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat(),
    }


@app.get("/")
def root():
    return {"message": "Riga Data Lake API - Building Energy Data (REA pilot)"}


@app.get(
    "/georiga/building-monthly-heat-series",
    tags=["Heat consumption"],
    summary="Building Monthly Heat Series (GeoRiga REA)",
    description=(
        "Source: GeoRiga REA MapServer "
        "(georiga.lv/server/rest/services/REA/MapServer), mirrored from TEF6_REA. "
        "Monthly per-building thermal-energy readings for Riga."
    ),
)
def get_building_monthly_heat_series(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    cadastre_number: str = Query(None),
):
    conn = _connect()
    try:
        cur = conn.cursor()

        if cadastre_number:
            cur.execute(BUILDINGS_BY_CADASTRE_QUERY, (cadastre_number,))
            rows = [dict(zip(BUILDINGS_COLUMNS, row)) for row in cur.fetchall()]
            cur.close()
            if not rows:
                raise HTTPException(status_code=404, detail="No heating data found for this cadastre number")
            return {"cadastre_number": cadastre_number, "count": len(rows), "data": rows}

        cur.execute(COUNT_QUERY)
        total = cur.fetchone()[0]

        cur.execute(BUILDINGS_QUERY, (limit, offset))
        rows = [dict(zip(BUILDINGS_COLUMNS, row)) for row in cur.fetchall()]
        cur.close()
    finally:
        conn.close()

    return {"total": total, "limit": limit, "offset": offset, "data": rows}
