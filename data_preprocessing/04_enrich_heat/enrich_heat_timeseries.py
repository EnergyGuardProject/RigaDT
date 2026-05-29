"""
Enrich GeoJSON features with REA heat consumption timeseries from local sources.
Uses REA JSON export as primary source, with local cache as fallback.
No API queries are made during the pipeline (deterministic, offline-capable).

Usage:
python enrich_heat_consumption_parallel.py --input ./script_pipeline/all_buildings.json --output ./script_pipeline/all_buildings_with_heat.json --rea-json ./script_pipeline/output/rea_all_features.json

Resolution order:
1. REA JSON export (5531 records, authoritative source)
2. Local cache (persisted timeseries from previous runs)
3. None (features not in REA or cache remain with None value)
"""

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set, List
from collections import defaultdict
SUMMER_MONTHS = tuple(range(5, 11))
NON_SUMMER_MONTHS = (1, 2, 3, 4, 11, 12)
CURRENT_YEAR = datetime.now(timezone.utc).year
YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def normalize_cadastre(value: Any) -> Optional[str]:
    """Normalize cadastre number to standard format."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return None
    if len(digits) < 14:
        digits = digits.zfill(14)
    return digits


def load_rea_json_lookup(json_path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    """Load REA GeoJSON export and build cadastre->feature lookup."""
    if not json_path or not json_path.exists():
        return {}
    
    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"Warning: could not load REA JSON {json_path}: {exc}")
        return {}
    
    features = data.get("features", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    lookup: Dict[str, Dict[str, Any]] = {}
    
    for feature in features:
        if not isinstance(feature, dict):
            continue
        attrs = feature.get("attributes", {}) or {}
        
        # Try common cadastre field names
        cadastre_raw = attrs.get("cadastrename") or attrs.get("cadastrena") or attrs.get("CODE")
        cadastre = normalize_cadastre(cadastre_raw)
        
        if cadastre:
            lookup[cadastre] = feature
    
    print(f"Loaded {len(lookup)} cadastre features from REA JSON: {json_path}")
    return lookup


def extract_timeseries_from_rea_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract heat timeseries from a REA feature's values_json attribute."""
    if not feature:
        return None
    
    attrs = feature.get("attributes", {})
    values_json = attrs.get("values_json")
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
    years: Set[int] = set()

    for key, value in timeseries.items():
        key_str = str(key).strip()
        normalized[key_str] = value
        match = YEAR_MONTH_RE.match(key_str)
        if not match:
            continue
        year = int(match.group(1))
        years.add(year)

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


def _looks_like_cadastre_key(key: str) -> bool:
    digits = "".join(ch for ch in str(key) if ch.isdigit())
    return len(digits) >= 11


def load_local_cache(cache_path: Optional[Path]) -> Dict[str, Optional[Dict[str, Any]]]:
    """Load local heat cache from JSON. Supports mapping and simple list forms."""
    if not cache_path:
        return {}
    if not cache_path.exists():
        print(f"No cache file found at {cache_path}; starting cold.")
        return {}

    try:
        with cache_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"Warning: could not read cache file {cache_path}: {exc}")
        return {}

    cache: Dict[str, Optional[Dict[str, Any]]] = {}

    # Format A: {"cache": {"010...": {...}|null}}
    if isinstance(payload, dict) and isinstance(payload.get("cache"), dict):
        source_map = payload.get("cache", {})
        for raw_key, raw_value in source_map.items():
            cad = normalize_cadastre(raw_key)
            if not cad:
                continue
            cache[cad] = fill_missing_months(raw_value) if isinstance(raw_value, dict) else None
        print(f"Loaded {len(cache)} cached cadastre entries from {cache_path}")
        return cache

    # Format B: {"010...": {...}|null}
    if isinstance(payload, dict):
        for raw_key, raw_value in payload.items():
            if not _looks_like_cadastre_key(raw_key):
                continue
            cad = normalize_cadastre(raw_key)
            if not cad:
                continue
            cache[cad] = fill_missing_months(raw_value) if isinstance(raw_value, dict) else None
        if cache:
            print(f"Loaded {len(cache)} cached cadastre entries from {cache_path}")
        return cache

    # Format C: [{"CODE": ..., "heat_consumption_timeseries": {...}}]
    if isinstance(payload, list):
        for row in payload:
            if not isinstance(row, dict):
                continue
            cad = normalize_cadastre(
                row.get("CODE")
                or row.get("cadastre")
                or row.get("cadastrename")
                or row.get("Kadastra Nr.")
            )
            if not cad:
                continue
            ts = row.get("heat_consumption_timeseries")
            cache[cad] = fill_missing_months(ts) if isinstance(ts, dict) else None
        if cache:
            print(f"Loaded {len(cache)} cached cadastre entries from {cache_path}")
        return cache

    print(f"Warning: unsupported cache format in {cache_path}; ignoring cache.")
    return {}


def save_local_cache(cache_path: Optional[Path], cache: Dict[str, Optional[Dict[str, Any]]]) -> None:
    if not cache_path:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {k: cache[k] for k in sorted(cache.keys())}
    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"Saved cache with {len(serializable)} entries to {cache_path}")





def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parallel REA heat consumption enrichment (10-20x faster)"
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
        "--limit",
        type=int,
        default=0,
        help="Process only first N features (0 means all).",
    )
    parser.add_argument(
        "--cache-file",
        default="",
        help=(
            "Optional JSON cache path for heat timeseries. "
            "If provided, timeseries from cache are used and updated with REA data."
        ),
    )
    parser.add_argument(
        "--rea-json",
        default="",
        help=(
            "Path to REA GeoJSON export (complete download from API). "
            "If provided, this is the source of truth; cadastres not in this JSON will not be queried."
        ),
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    print(f"Loading GeoJSON: {input_path}")
    start_time = time.time()
    
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    if not isinstance(features, list):
        raise ValueError("Invalid GeoJSON: features is not a list")

    max_count = args.limit if args.limit and args.limit > 0 else len(features)
    to_process = features[:max_count]
    cache_path = Path(args.cache_file) if args.cache_file else None

    # Step 1: Extract and deduplicate cadastre numbers
    print(f"\nStep 1: Deduplicating {len(to_process)} features...")
    cadastre_map = {}  # cadastre -> list of feature indices
    unique_cadastres = set()
    missing_cadastres = 0

    for idx, feat in enumerate(to_process):
        props = feat.get("properties", {})
        raw_cad = props.get(args.cadastre_field)
        cadastre = normalize_cadastre(raw_cad)
        
        if cadastre:
            if cadastre not in cadastre_map:
                cadastre_map[cadastre] = []
            cadastre_map[cadastre].append(idx)
            unique_cadastres.add(cadastre)
        else:
            missing_cadastres += 1

    print(f"  Total features: {len(to_process)}")
    print(f"  Unique cadastres: {len(unique_cadastres)}")
    print(f"  Missing cadastres: {missing_cadastres}")
    print(f"  Reduction factor: {len(to_process) / len(unique_cadastres):.1f}x")

    # Step 2: Resolve from REA JSON lookup, cache, then API
    rea_json_path = Path(args.rea_json) if args.rea_json else None
    rea_lookup = load_rea_json_lookup(rea_json_path)
    
    local_cache = load_local_cache(cache_path)
    
    # Extract timeseries from REA JSON features and populate cache
    rea_hits = 0
    rea_misses = 0
    for cad in unique_cadastres:
        if cad in rea_lookup:
            feat = rea_lookup[cad]
            values_json_raw = feat.get("attributes", {}).get("values_json") if feat else None
            if values_json_raw:
                try:
                    if isinstance(values_json_raw, str):
                        ts = json.loads(values_json_raw)
                    else:
                        ts = values_json_raw
                    ts = fill_missing_months(ts) if isinstance(ts, dict) else None
                    if ts and cad not in local_cache:
                        local_cache[cad] = ts
                        rea_hits += 1
                    elif not ts:
                        rea_misses += 1
                except Exception:
                    rea_misses += 1
            else:
                rea_misses += 1
    
    cached_hits = sum(1 for v in local_cache.values() if v is not None)
    cached_misses = len(local_cache) - cached_hits
    
    print(
        f"\nStep 2: REA + cache resolution (local-only): "
        f"rea_json={len(rea_lookup)} features, "
        f"rea_hits={rea_hits}, "
        f"cache_total={len(local_cache)} (with_data={cached_hits}, no_data={cached_misses})"
    )
    
    # Save updated cache
    merged_cache = dict(local_cache)
    save_local_cache(cache_path, merged_cache)

    # Step 3: Apply results to features
    print(f"\nStep 3: Applying results to features...")
    
    for cadastre, timeseries in merged_cache.items():
        if cadastre in cadastre_map:
            for feat_idx in cadastre_map[cadastre]:
                to_process[feat_idx]["properties"]["heat_consumption_timeseries"] = timeseries

    # Add missing cadastres with None
    for idx, feat in enumerate(to_process):
        if "heat_consumption_timeseries" not in feat.get("properties", {}):
            feat["properties"]["heat_consumption_timeseries"] = None

    # Step 4: Save
    print(f"  Saving to: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Summary
    elapsed = time.time() - start_time
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total time: {elapsed:.1f}s")
    print(f"Features processed: {len(to_process)}")
    print(f"Unique cadastres resolved: {len(unique_cadastres)}")
    print(f"Cadastres from REA JSON: {rea_hits}")
    print(f"Cadastres from cache: {cached_hits}")
    print(f"Cadastres with no data: {cached_misses}")
    print(f"Cache used: {cache_path if cache_path else 'disabled'}")
    print(f"API queries executed: 0 (local-only mode)")
    
    print(f"\nOutput: {output_path}")
    print(f"File size: {output_path.stat().st_size / (1024*1024):.1f} MB")


if __name__ == "__main__":
    main()
