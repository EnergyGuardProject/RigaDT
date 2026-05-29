import json
from collections import Counter
from pathlib import Path

base_file = Path("merged_output_residential/ALL_RESIDENTIAL_BUILDINGS.geojson")
heat_file = Path("script_pipeline/all_buildings_with_heat.json")


def load_geojson(path: Path):
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data, data.get("features", [])


def not_empty(v):
    return v is not None and str(v).strip() != ""


base_data, base_feats = load_geojson(base_file)
heat_data, heat_feats = load_geojson(heat_file)

base_codes = [f.get("properties", {}).get("CODE") for f in base_feats]
heat_codes = [f.get("properties", {}).get("CODE") for f in heat_feats]
base_non_null_codes = [c for c in base_codes if not_empty(c)]
heat_non_null_codes = [c for c in heat_codes if not_empty(c)]

print("=== OUTPUT EVALUATION ===")
print(f"base_file_exists={base_file.exists()} heat_file_exists={heat_file.exists()}")
print(f"base_features={len(base_feats)} heat_features={len(heat_feats)}")
print(f"base_size_mb={base_file.stat().st_size / (1024 * 1024):.2f}")
print(f"heat_size_mb={heat_file.stat().st_size / (1024 * 1024):.2f}")
print(f"base_unique_codes={len(set(base_non_null_codes))}")
print(f"heat_unique_codes={len(set(heat_non_null_codes))}")
print(f"base_duplicate_code_features={len(base_non_null_codes) - len(set(base_non_null_codes))}")
print(f"heat_duplicate_code_features={len(heat_non_null_codes) - len(set(heat_non_null_codes))}")
print(f"same_feature_count={len(base_feats) == len(heat_feats)}")
print(f"same_code_set={set(base_non_null_codes) == set(heat_non_null_codes)}")

fields = ["building_use", "building_kind", "building_area", "building_material", "heavy_light", "building_count"]
for field in fields:
    filled = sum(1 for f in base_feats if not_empty(f.get("properties", {}).get(field)))
    pct = (filled / len(base_feats) * 100) if base_feats else 0
    print(f"base_field_fill_{field}={filled}/{len(base_feats)} ({pct:.2f}%)")

heat_non_null = 0
heat_null = 0
year_len_dist = Counter()

for feat in heat_feats:
    ts = feat.get("properties", {}).get("heat_consumption_timeseries")
    if isinstance(ts, dict) and ts:
        heat_non_null += 1
        year_len_dist[len(ts)] += 1
    else:
        heat_null += 1

heat_pct = (heat_non_null / len(heat_feats) * 100) if heat_feats else 0
print(f"heat_timeseries_non_null={heat_non_null}/{len(heat_feats)} ({heat_pct:.2f}%)")
print(f"heat_timeseries_null={heat_null}")
print(f"heat_timeseries_year_count_distribution={dict(year_len_dist)}")

base_geom = Counter(f.get("geometry", {}).get("type", "None") for f in base_feats)
heat_geom = Counter(f.get("geometry", {}).get("type", "None") for f in heat_feats)
print(f"base_geometry_types={dict(base_geom)}")
print(f"heat_geometry_types={dict(heat_geom)}")
