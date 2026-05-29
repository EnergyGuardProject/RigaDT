import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

BASE_URL = "https://georiga.lv/server/rest/services/REA/MapServer/0/query"
SUMMER_MONTHS = tuple(range(5, 11))
NON_SUMMER_MONTHS = (1, 2, 3, 4, 11, 12)
CURRENT_YEAR = datetime.now(timezone.utc).year
YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def normalize_cadastre(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return None
    # REA cadastral names are typically 14 digits; keep longer values as-is.
    if len(digits) < 14:
        digits = digits.zfill(14)
    return digits


def build_query_url(cadastre: str) -> str:
    params = {
        "where": f"cadastrename='{cadastre}'",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "json",
    }
    return f"{BASE_URL}?{urlencode(params)}"


def fetch_feature_payload(cadastre: str, timeout: int, retries: int) -> Dict[str, Any]:
    last_err: Optional[Exception] = None
    url = build_query_url(cadastre)
    req = Request(url, headers={"User-Agent": "EGuard-ETL/1.0"})

    for attempt in range(1, retries + 1):
        try:
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            if data.get("error"):
                raise RuntimeError(f"API error: {data['error']}")
            return data
        except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(min(1.0 * attempt, 3.0))

    raise RuntimeError(f"Failed for cadastre {cadastre}: {last_err}")


def extract_timeseries(payload: Dict[str, Any], cadastre: str) -> Optional[Dict[str, Any]]:
    features = payload.get("features", [])
    if not features:
        return None

    # Prefer exact cadastre match if multiple features are returned.
    selected = None
    for feat in features:
        attrs = feat.get("attributes", {})
        if str(attrs.get("cadastrename", "")).strip() == cadastre:
            selected = feat
            break
    if selected is None:
        selected = features[0]

    values_json = selected.get("attributes", {}).get("values_json")
    if not values_json:
        return None

    if isinstance(values_json, dict):
        return values_json

    if isinstance(values_json, str):
        try:
            parsed = json.loads(values_json)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    return None


def fill_missing_months(timeseries: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Fill missing months with 0 for past years only; never fill current/future years."""
    if not isinstance(timeseries, dict):
        return timeseries

    normalized: Dict[str, Any] = {}
    years = set()

    for key, value in timeseries.items():
        key_str = str(key).strip()
        normalized[key_str] = value
        match = YEAR_MONTH_RE.match(key_str)
        if not match:
            continue
        years.add(int(match.group(1)))

    for year in years:
        if year >= CURRENT_YEAR:
            continue
        for month in SUMMER_MONTHS:
            ym = f"{year}-{month:02d}"
            if ym not in normalized:
                normalized[ym] = 0

    for year in years:
        if year >= CURRENT_YEAR:
            continue
        for month in NON_SUMMER_MONTHS:
            ym = f"{year}-{month:02d}"
            if ym not in normalized:
                normalized[ym] = 0

    return {k: normalized[k] for k in sorted(normalized.keys())}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich GeoJSON features with REA heat consumption time series from GeoRiga API."
        )
    )
    parser.add_argument(
        "--input",
        default="./script_pipeline/all_buildings.json",
        help="Input GeoJSON file path.",
    )
    parser.add_argument(
        "--output",
        default="./script_pipeline/all_buildings_with_heat.json",
        help="Output enriched GeoJSON file path.",
    )
    parser.add_argument(
        "--cadastre-field",
        default="CODE",
        help="Feature properties field to use for cadastre number.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retry attempts per cadastre.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.05,
        help="Delay between API calls in seconds.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only first N features (0 means all).",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    if not isinstance(features, list):
        raise ValueError("Invalid GeoJSON: features is not a list")

    max_count = args.limit if args.limit and args.limit > 0 else len(features)
    to_process = features[:max_count]

    cache: Dict[str, Optional[Dict[str, Any]]] = {}
    hits = 0
    misses = 0
    errors = 0

    for idx, feat in enumerate(to_process, 1):
        props = feat.setdefault("properties", {})
        raw_cad = props.get(args.cadastre_field)
        cadastre = normalize_cadastre(raw_cad)

        if not cadastre:
            props["heat_consumption_timeseries"] = None
            misses += 1
            continue

        if cadastre not in cache:
            try:
                payload = fetch_feature_payload(cadastre, timeout=args.timeout, retries=args.retries)
                cache[cadastre] = fill_missing_months(extract_timeseries(payload, cadastre))
                time.sleep(args.sleep)
            except Exception as exc:
                cache[cadastre] = None
                errors += 1
                print(f"[{idx}/{max_count}] ERROR {cadastre}: {exc}")

        ts = cache[cadastre]
        props["heat_consumption_timeseries"] = ts

        if ts is None:
            misses += 1
        else:
            hits += 1

        if idx % 200 == 0 or idx == max_count:
            print(
                f"Processed {idx}/{max_count} | hits={hits} misses={misses} errors={errors} unique_queries={len(cache)}"
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("\nDone")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Features processed: {max_count}")
    print(f"Hits: {hits}")
    print(f"Misses: {misses}")
    print(f"Errors: {errors}")
    print(f"Unique cadastre queries: {len(cache)}")


if __name__ == "__main__":
    main()
