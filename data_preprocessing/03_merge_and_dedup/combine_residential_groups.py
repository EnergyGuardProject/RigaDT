"""
Script to merge all GeoJSON files in merged_output_residential into a single file.
"""

import argparse
import json
import os
from pathlib import Path

def merge_geojson_files(input_folder, output_file, include_pattern):
    """Merge GeoJSON files in a folder into a single file."""

    output_name = Path(output_file).name
    geojson_files = [
        p for p in sorted(Path(input_folder).glob(include_pattern))
        if p.name != output_name
    ]
    
    if not geojson_files:
        print(f"No GeoJSON files found in {input_folder}")
        return
    
    print(f"Found {len(geojson_files)} GeoJSON files (pattern: {include_pattern})")
    print("Merging...")
    
    # Initialize merged GeoJSON
    merged_geojson = {
        "type": "FeatureCollection",
        "name": "Merged_Residential_Buildings",
        "features": []
    }
    
    total_features = 0
    
    # Process each file
    for geojson_file in geojson_files:
        print(f"  Processing: {geojson_file.name}")
        
        try:
            with open(geojson_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            features = data.get('features', [])
            merged_geojson['features'].extend(features)
            total_features += len(features)
            
        except Exception as e:
            print(f"    ERROR reading {geojson_file.name}: {e}")
            continue
    
    print(f"\nTotal features merged: {total_features}")
    
    # Save merged file
    print(f"Saving to: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(merged_geojson, f, ensure_ascii=False, indent=2)
    
    print(f"✓ Merge complete!")
    print(f"  File size: {os.path.getsize(output_file) / (1024*1024):.2f} MB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Merge canonical residential GeoJSON outputs into a single file."
    )
    parser.add_argument(
        "--input-folder",
        default="./merged_output_residential",
        help="Folder containing per-group merged GeoJSON files.",
    )
    parser.add_argument(
        "--output-file",
        default="./merged_output_residential/ALL_RESIDENTIAL_BUILDINGS.geojson",
        help="Path to write the merged final GeoJSON.",
    )
    parser.add_argument(
        "--include-pattern",
        default="merged_ExportCadGroup_*_KKBuilding.geojson",
        help="Glob for files to include (relative to input-folder).",
    )
    args = parser.parse_args()

    input_folder = args.input_folder
    output_file = args.output_file
    include_pattern = args.include_pattern
    
    if not os.path.exists(input_folder):
        print(f"ERROR: Folder not found: {input_folder}")
        exit(1)
    
    merge_geojson_files(input_folder, output_file, include_pattern)
