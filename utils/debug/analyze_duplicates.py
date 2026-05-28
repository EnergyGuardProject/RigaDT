"""
Analyze duplicate features in residential GeoJSON files.
Identifies buildings with the same CODE that appear multiple times as separate features.

USAGE:
python analyze_duplicates.py --input ./merged_output_residential/ALL_RESIDENTIAL_BUILDINGS.geojson [--output analysis_report.txt]
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple


def analyze_geojson_duplicates(geojson_path: str, output_report: str = None):
    """Analyze and report on duplicate CODE values in GeoJSON features."""
    
    print(f"Loading: {geojson_path}")
    with open(geojson_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    features = data.get('features', [])
    print(f"Total features: {len(features)}\n")
    
    # Track CODE values
    code_map = defaultdict(list)  # CODE -> list of (feature_idx, feature)
    codes_without_match = []
    
    for idx, feature in enumerate(features):
        props = feature.get('properties', {})
        code = props.get('CODE')
        
        if code:
            code_map[code].append((idx, feature))
        else:
            codes_without_match.append(idx)
    
    # Analysis
    unique_codes = len(code_map)
    duplicated_codes = {code: indices for code, indices in code_map.items() if len(indices) > 1}
    num_duplicated = len(duplicated_codes)
    num_duplicate_features = sum(len(indices) - 1 for indices in duplicated_codes.values())
    
    # Report
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("DUPLICATE ANALYSIS REPORT")
    report_lines.append("=" * 80)
    report_lines.append(f"\nTotal features: {len(features)}")
    report_lines.append(f"Unique CODE values: {unique_codes}")
    report_lines.append(f"Features without CODE: {len(codes_without_match)}")
    report_lines.append(f"\nDuplicate Statistics:")
    report_lines.append(f"  CODEs with duplicates: {num_duplicated}")
    report_lines.append(f"  Extra duplicate features: {num_duplicate_features}")
    report_lines.append(f"  Expected unique features (after dedup): {len(features) - num_duplicate_features}")
    
    # Distribution of duplicates
    dup_counts = defaultdict(int)
    for code, indices in duplicated_codes.items():
        dup_counts[len(indices)] += 1
    
    report_lines.append(f"\nDuplicate Distribution:")
    for count in sorted(dup_counts.keys()):
        report_lines.append(f"  {count} copies: {dup_counts[count]} CODEs")
    
    # Sample duplicates
    report_lines.append(f"\n\nSample Duplicates (first 20):")
    report_lines.append("-" * 80)
    
    for i, (code, indices) in enumerate(sorted(duplicated_codes.items())[:20]):
        num_copies = len(indices)
        report_lines.append(f"\nCODE: {code} (appears {num_copies} times)")
        
        for copy_idx, (feature_idx, feature) in enumerate(indices):
            props = feature.get('properties', {})
            geom = feature.get('geometry', {})
            geom_type = geom.get('type', 'N/A')
            
            # Extract key properties
            building_count = props.get('building_count', 'N/A')
            building_use = props.get('building_use', 'N/A')
            building_kind = props.get('building_kind', 'N/A')
            area = props.get('building_area', 'N/A')
            
            report_lines.append(f"  Copy {copy_idx + 1}:")
            report_lines.append(f"    Feature index: {feature_idx}")
            report_lines.append(f"    Geometry type: {geom_type}")
            report_lines.append(f"    Building count: {building_count}")
            report_lines.append(f"    Building use: {building_use}")
            report_lines.append(f"    Building kind: {building_kind}")
            report_lines.append(f"    Area: {area}")
    
    # Detailed duplicates (for very duplicated codes)
    heavily_duplicated = [(code, indices) for code, indices in duplicated_codes.items() if len(indices) > 3]
    if heavily_duplicated:
        report_lines.append(f"\n\nHeavily Duplicated CODEs (>3 copies): {len(heavily_duplicated)}")
        report_lines.append("-" * 80)
        for code, indices in sorted(heavily_duplicated, key=lambda x: -len(x[1]))[:10]:
            report_lines.append(f"\nCODE: {code} ({len(indices)} copies)")
            for copy_idx, (feature_idx, feature) in enumerate(indices):
                props = feature.get('properties', {})
                geom = feature.get('geometry', {})
                geom_type = geom.get('type', 'N/A')
                report_lines.append(f"  [{copy_idx + 1}] index={feature_idx}, geom={geom_type}")
    
    # Possible patterns
    report_lines.append(f"\n\nPossible Causes:")
    report_lines.append("-" * 80)
    
    # Check if duplicates share geometry or properties
    report_lines.append("\nAnalyzing duplicate patterns...")
    
    same_geom_count = 0
    same_props_count = 0
    split_geom_count = 0
    
    for code, indices in duplicated_codes.items():
        features_list = [f for _, f in indices]
        
        # Check geometry
        geoms = [str(f.get('geometry')) for f in features_list]
        if len(set(geoms)) == 1:
            same_geom_count += 1
        else:
            split_geom_count += 1
        
        # Check key properties
        props_list = [f.get('properties', {}) for f in features_list]
        uses = [p.get('building_use') for p in props_list]
        if len(set(str(u) for u in uses)) == 1:
            same_props_count += 1
    
    report_lines.append(f"  CODEs with identical geometry: {same_geom_count}")
    report_lines.append(f"  CODEs with split geometry: {split_geom_count}")
    report_lines.append(f"  CODEs with same building_use: {same_props_count}")
    
    report_lines.append("\n" + "=" * 80)
    
    # Print and save
    report_text = "\n".join(report_lines)
    print(report_text)
    
    if output_report:
        with open(output_report, 'w', encoding='utf-8') as f:
            f.write(report_text)
        print(f"\n✓ Report saved to: {output_report}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze duplicate features in GeoJSON")
    parser.add_argument(
        "--input",
        default="./merged_output_residential/ALL_RESIDENTIAL_BUILDINGS.geojson",
        help="Path to input GeoJSON file"
    )
    parser.add_argument(
        "--output",
        help="Path to save analysis report (optional)"
    )
    
    args = parser.parse_args()
    
    if not Path(args.input).exists():
        print(f"ERROR: File not found: {args.input}")
        exit(1)
    
    analyze_geojson_duplicates(args.input, args.output)
