"""
Deduplicate residential GeoJSON files by CODE.
Removes features with duplicate CODE values.

USAGE:
python deduplicate_geojson.py --input ./merged_output_residential/ALL_RESIDENTIAL_BUILDINGS.geojson --output ./merged_output_residential/ALL_RESIDENTIAL_BUILDINGS_DEDUP.geojson
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, List


def deduplicate_geojson(input_path: str, output_path: str):
    """Remove duplicate features based on CODE."""
    
    print(f"Loading: {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    features = data.get('features', [])
    print(f"Total features: {len(features)}")
    
    # Group by CODE
    code_map = defaultdict(list)
    features_without_code = []
    
    for feature in features:
        code = feature.get('properties', {}).get('CODE')
        if code:
            code_map[code].append(feature)
        else:
            features_without_code.append(feature)
    
    unique_codes = len(code_map)
    duplicate_codes = {code: feats for code, feats in code_map.items() if len(feats) > 1}
    num_duplicates = sum(len(feats) - 1 for feats in duplicate_codes.values())
    
    print(f"\nAnalysis:")
    print(f"  Unique CODEs: {unique_codes}")
    print(f"  CODEs with duplicates: {len(duplicate_codes)}")
    print(f"  Duplicate features to remove: {num_duplicates}")
    print(f"  Expected output features: {len(features) - num_duplicates}")
    
    # Deduplicate (keep-first only)
    deduped_features = []
    for code, features_list in code_map.items():
        deduped_features.append(features_list[0])
    print(f"\nStrategy: keep-first")
    print(f"  → Kept first feature for each CODE")
    
    # Add features without CODE (keep as-is)
    deduped_features.extend(features_without_code)
    
    # Write output
    output_data = data.copy()
    output_data['features'] = deduped_features
    
    print(f"\nWriting output...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    output_size_mb = Path(output_path).stat().st_size / (1024 * 1024)
    print(f"✓ Deduped GeoJSON saved to: {output_path}")
    print(f"  Features: {len(features)} → {len(deduped_features)}")
    print(f"  File size: {output_size_mb:.2f} MB")
    
    # Statistics
    print(f"\nDeduplication Summary:")
    print(f"  Removed features: {len(features) - len(deduped_features)}")
    print(f"  Reduction: {(num_duplicates / len(features) * 100):.1f}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deduplicate features in GeoJSON by CODE")
    parser.add_argument(
        "--input",
        default="./merged_output_residential/ALL_RESIDENTIAL_BUILDINGS.geojson",
        help="Path to input GeoJSON file"
    )
    parser.add_argument(
        "--output",
        default="./merged_output_residential/ALL_RESIDENTIAL_BUILDINGS_DEDUP.geojson",
        help="Path to save deduplicated GeoJSON"
    )
    
    args = parser.parse_args()
    
    if not Path(args.input).exists():
        print(f"ERROR: File not found: {args.input}")
        exit(1)
    
    deduplicate_geojson(args.input, args.output)
