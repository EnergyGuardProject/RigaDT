
import logging
import os

import psycopg2
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

load_dotenv()

logger = logging.getLogger(__name__)


def _required_setting(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

app = FastAPI(
    title="Riga Data Lake API",
    description=(
        "Data endpoints for the Riga TEF pilot, one per source dataset from the "
        "GeoRiga / data.gov.lv open-data catalogue and the EnergyGuard consortium "
        "(building audits, heat consumption, meteorology, air quality, energy "
        "certificates, spatial/cadastral data, and more)."
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


@app.get("/")
def root():
    return {"message": "Riga Data Lake API - Building Energy Data (REA pilot)"}


@app.get(
    "/georiga/building-monthly-heat-series",
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
