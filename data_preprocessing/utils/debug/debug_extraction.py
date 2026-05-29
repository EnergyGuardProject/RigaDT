"""
Debug: Show what's actually in the building_data fields.
"""

import json
from pathlib import Path

geojson_path = "./merged_output_residential/ALL_RESIDENTIAL_BUILDINGS.geojson"

print(f"Loading: {geojson_path}")
with open(geojson_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

features = data.get('features', [])
print(f"Total features: {len(features)}\n")

# Sample first feature with data
feature = features[0]
props = feature.get('properties', {})
bd = props.get('building_data', [])

if bd and len(bd) > 0:
    first_building = bd[0]
    print(f"CODE: {props.get('CODE')}")
    print(f"\nKeys in building_data[0]:")
    print("=" * 80)
    
    for key in sorted(first_building.keys()):
        value = first_building[key]
        # Show only non-empty values and keys of interest
        if value and (
            'UseKindName' in key or 
            'KindName' in key or 
            'KindId' in key or 
            'Area' in key or
            'MaterialKindName' in key or
            'residential' in key.lower()
        ):
            print(f"{key}: {value}")
    
    print("\n" + "=" * 80)
    print("Looking for extraction patterns:")
    print("=" * 80)
    
    # Test the extraction logic
    print("\nTesting extraction logic from merge script:")
    
    material_kind_name = None
    building_use_name = None
    building_kind_name = None
    building_kind_id = None
    building_area = None
    
    for key in first_building.keys():
        value = first_building.get(key, '')
        
        if 'MaterialKindName' in key:
            print(f"  Found MaterialKindName in '{key}': {value}")
            material_kind_name = value
        if 'BuildingUseKindName' in key:
            print(f"  Found BuildingUseKindName in '{key}': {value}")
            building_use_name = value
        if 'BuildingKindName' in key:
            print(f"  Found BuildingKindName in '{key}': {value}")
            building_kind_name = value
        if 'BuildingKindId' in key:
            print(f"  Found BuildingKindId in '{key}': {value}")
            building_kind_id = value
        if 'Area' in key and not building_area:
            print(f"  Found Area in '{key}': {value}")
            building_area = value
    
    print("\nExtraction results:")
    print(f"  material_kind_name: {material_kind_name}")
    print(f"  building_use_name: {building_use_name}")
    print(f"  building_kind_name: {building_kind_name}")
    print(f"  building_kind_id: {building_kind_id}")
    print(f"  building_area: {building_area}")
else:
    print("No building_data found!")
