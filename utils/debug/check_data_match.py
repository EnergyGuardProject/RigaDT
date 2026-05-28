"""
Analyze why building data matching failed.
Shows matched vs unmatched features and their properties.
"""

import json
from pathlib import Path
from collections import defaultdict

geojson_path = "./merged_output_residential/ALL_RESIDENTIAL_BUILDINGS.geojson"

print(f"Loading: {geojson_path}")
with open(geojson_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

features = data.get('features', [])
print(f"Total features: {len(features)}\n")

# Categorize by whether they have building data
has_building_data = []
no_building_data = []
has_building_data_fields = []

for feature in features:
    props = feature.get('properties', {})
    
    # Check if there's any building data
    has_use = props.get('building_use') is not None
    has_kind = props.get('building_kind') is not None
    has_area = props.get('building_area') is not None
    has_material = props.get('building_material') is not None
    has_bd = props.get('building_data') is not None
    
    if has_use or has_kind or has_area or has_material or has_bd:
        has_building_data.append(feature)
        if has_bd:
            has_building_data_fields.append(props.get('building_data'))
    else:
        no_building_data.append(feature)

print(f"Features WITH building data: {len(has_building_data)}/{len(features)} ({len(has_building_data)/len(features)*100:.1f}%)")
print(f"Features WITHOUT building data: {len(no_building_data)}/{len(features)} ({len(no_building_data)/len(features)*100:.1f}%)")
print(f"Features with building_data field: {len(has_building_data_fields)}")

# Show sample of features WITH data
print("\n" + "=" * 80)
print("Sample Features WITH Building Data:")
print("=" * 80)

for i, feature in enumerate(has_building_data[:3]):
    props = feature.get('properties', {})
    print(f"\nFeature {i+1} (CODE: {props.get('CODE')}):")
    print(f"  building_use: {props.get('building_use')}")
    print(f"  building_kind: {props.get('building_kind')}")
    print(f"  building_area: {props.get('building_area')}")
    print(f"  building_material: {props.get('building_material')}")
    print(f"  building_count: {props.get('building_count')}")
    if props.get('building_data'):
        bd = props.get('building_data')[0]
        print(f"  building_data keys: {list(bd.keys())[:5]}...")

# Show sample of features WITHOUT data
print("\n" + "=" * 80)
print("Sample Features WITHOUT Building Data:")
print("=" * 80)

for i, feature in enumerate(no_building_data[:3]):
    props = feature.get('properties', {})
    print(f"\nFeature {i+1} (CODE: {props.get('CODE')}):")
    print(f"  All available properties: {list(props.keys())}")

# Check for pattern
print("\n" + "=" * 80)
print("Analysis:")
print("=" * 80)

if len(has_building_data) == 0:
    print("\n⚠️  NO features have building data!")
    print("This suggests CSV matching failed completely.")
    print("\nPossible causes:")
    print("  1. CSV files are empty or missing")
    print("  2. Cadastre number format mismatch (e.g., leading zeros)")
    print("  3. CSV column names changed")
    print("  4. Building classification (residential filter) excluded data")
elif len(has_building_data) < len(features) * 0.5:
    print(f"\n⚠️  Only {len(has_building_data)/len(features)*100:.1f}% of features have building data")
    print("CSV matching had low success rate.")
else:
    print(f"\n✓ Good coverage: {len(has_building_data)/len(features)*100:.1f}% of features matched")
