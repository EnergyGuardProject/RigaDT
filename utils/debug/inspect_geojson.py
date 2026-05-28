"""
Quick inspection of the merged residential buildings GeoJSON.
Shows sample features and their structure.
"""

import json
from pathlib import Path

geojson_path = "./merged_output_residential/ALL_RESIDENTIAL_BUILDINGS.geojson"

print(f"Loading: {geojson_path}")
with open(geojson_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

features = data.get('features', [])
print(f"Total features: {len(features)}\n")

# Sample a few features
print("Sample Features (first 3):")
print("=" * 80)

for i, feature in enumerate(features[:3]):
    props = feature.get('properties', {})
    print(f"\nFeature {i+1}:")
    print(f"  CODE: {props.get('CODE')}")
    print(f"  building_count: {props.get('building_count')}")
    print(f"  building_use: {props.get('building_use')}")
    print(f"  building_kind: {props.get('building_kind')}")
    print(f"  building_area: {props.get('building_area')}")
    print(f"  geometry type: {feature.get('geometry', {}).get('type')}")

# Check building_count distribution
print("\n" + "=" * 80)
print("Building Count Distribution:")
building_counts = {}
total_buildings = 0

for feature in features:
    bc = feature.get('properties', {}).get('building_count', 0)
    if bc not in building_counts:
        building_counts[bc] = 0
    building_counts[bc] += 1
    if isinstance(bc, int):
        total_buildings += bc

for count in sorted(building_counts.keys()):
    num_features = building_counts[count]
    print(f"  {count} building(s): {num_features} features", end="")
    if count == 0:
        print(" (no building data found)")
    else:
        print()

print(f"\nTotal features: {len(features)}")
print(f"Total buildings (sum of building_count): {total_buildings}")
print(f"Average buildings per feature: {total_buildings / len(features):.2f}")
