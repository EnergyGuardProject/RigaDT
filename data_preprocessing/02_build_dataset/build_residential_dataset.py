"""
Script to merge cadastre data from building CSV files into GeoJSON files.

For each GeoJSON file in the 0001000_kk_shp folder:
- Read cadastre numbers (codes) from the GeoJSON
- Search all CSV files in the building folder
- Find matching cadastre numbers in CSV files
- Merge the building data into the GeoJSON properties

USAGE INSTRUCTIONS:

1. Default execution (uses default paths):
   python merge_cadastre_data.py

2. Custom paths (specify shapefile, building, and output directories):
   python merge_cadastre_data.py ./0001000_kk_shp ./building ./merged_output

3. Example with specific paths:
   python merge_cadastre_data.py ./shapefiles ./buildings_data ./results

REQUIRED:
- GeoJSON files or shapefiles in the SHAPEFILE_BASE directory
- CSV files with cadastre numbers in the BUILDING_BASE directory
- Python packages: geopandas, pandas, tqdm

DEFAULT PATHS (if not provided):
- SHAPEFILE_BASE: ./0001000_kk_shp
- BUILDING_BASE: ./building or ./geojson_output
- OUTPUT_BASE: ./merged_output

OUTPUT:
- Merged GeoJSON files will be saved to OUTPUT_BASE directory
- Each file is named: merged_<parent_directory_name>.geojson
"""

import os
import json
import csv
import glob
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
import geopandas as gpd
import pandas as pd
from tqdm import tqdm
from material_classifier import classify_building_materials

# Paths - can be overridden by command line arguments
if len(sys.argv) > 1:
    SHAPEFILE_BASE = sys.argv[1]
else:
    SHAPEFILE_BASE = "./0001000_kk_shp"

if len(sys.argv) > 2:
    BUILDING_BASE = sys.argv[2]
else:
    BUILDING_BASE = "./building"

if len(sys.argv) > 3:
    OUTPUT_BASE = sys.argv[3]
else:
    OUTPUT_BASE = "./merged_output"

if len(sys.argv) > 4:
    HISTORICAL_CADASTRES_CSV = sys.argv[4]
else:
    HISTORICAL_CADASTRES_CSV = "./script_pipeline/historical_cadastre_lookup.csv"

# Verify paths exist
print(f"SHAPEFILE_BASE: {SHAPEFILE_BASE}")
print(f"  Exists: {os.path.exists(SHAPEFILE_BASE)}")
print(f"BUILDING_BASE: {BUILDING_BASE}")
print(f"  Exists: {os.path.exists(BUILDING_BASE)}")
print(f"HISTORICAL_CADASTRES_CSV: {HISTORICAL_CADASTRES_CSV}")
print(f"  Exists: {os.path.exists(HISTORICAL_CADASTRES_CSV)}")

# Create output directory
os.makedirs(OUTPUT_BASE, exist_ok=True)


def find_all_csv_files(building_folder: str) -> List[str]:
    """Find all CSV files in the building folder structure."""
    csv_files = []
    for root, dirs, files in os.walk(building_folder):
        for file in files:
            if file.endswith('.csv'):
                file_path = os.path.join(root, file)
                csv_files.append(file_path)
                print(f"  Found CSV: {file_path}")
    return csv_files


def read_csv_chunk(csv_file: str, cadastre_column: str = 'BuildingBasicData.BuildingCadastreNr', 
                   chunk_size: int = 10000) -> pd.DataFrame:
    """Read CSV file in chunks to handle large files."""
    try:
        # Read CSV in chunks
        chunks = []
        for chunk in pd.read_csv(csv_file, chunksize=chunk_size, low_memory=False, dtype=str):
            if cadastre_column in chunk.columns:
                # Filter out rows without cadastre number
                chunk_filtered = chunk[chunk[cadastre_column].notna()]
                if not chunk_filtered.empty:
                    chunks.append(chunk_filtered)
        
        if chunks:
            return pd.concat(chunks, ignore_index=True)
        else:
            return pd.DataFrame()
    except Exception as e:
        print(f"Error reading {csv_file}: {e}")
        return pd.DataFrame()


def normalize_cadastre(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    digits = ''.join(ch for ch in s if ch.isdigit())
    if not digits:
        return None
    if len(digits) < 14:
        digits = digits.zfill(14)
    return digits


def load_historical_cadastres(csv_path: str) -> Tuple[Set[str], Dict[str, str]]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Historical cadastre CSV not found: {csv_path}")

    allowed: Set[str] = set()
    addresses: Dict[str, str] = {}
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
        reader = csv.DictReader(f, dialect=dialect)
        if not reader.fieldnames:
            raise ValueError(f"Historical cadastre CSV has no headers: {csv_path}")

        candidates = ['Kadastra Nr.', 'Kadastra Nr', 'KadastraNr', 'CODE', reader.fieldnames[0]]
        cadastre_column = next((c for c in candidates if c in reader.fieldnames), None)
        if cadastre_column is None:
            raise ValueError(
                f"Could not find cadastre column in {csv_path}; headers={reader.fieldnames}"
            )
        address_column = next(
            (c for c in reader.fieldnames if c.lower() in {'address', 'adrese'}),
            None,
        )

        for row in reader:
            cad = normalize_cadastre(row.get(cadastre_column))
            if cad:
                allowed.add(cad)
                address = (row.get(address_column) or '').strip() if address_column else ''
                if address:
                    addresses[cad] = address

    if not allowed:
        raise ValueError(f"Historical cadastre CSV is empty or has no valid cadastre values: {csv_path}")

    return allowed, addresses


def build_cadastre_database(
    csv_files: List[str],
    allowed_cadastres: Optional[Set[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build a database of cadastre numbers from all CSV files."""
    cadastre_db = {}
    cadastre_column = 'BuildingBasicData.BuildingCadastreNr'
    filtered_by_historical = 0
    
    # Keywords to filter columns
    keywords = [
        'ExpedientArea',
        'TotalArea',
        'BuildingGroundFloors',
        'BuildingUndergroundFloors',
        'BuildingPregCount',
        'MaterialKindName',
        'FlatArea',
        'BuildingUseKindName',
        'BuildingKindName',
    'BuildingKindId'
    ]
    
    # Minimal residential keywords/prefixes based on dataset scan
    residential_text_stems = ['māja', 'dzīvojam', 'dzīvokļ']  # Added dzīvokļ to catch dzīvokļu/dzīvokļa (apartments)
    residential_id_prefixes = ['1110', '112', '113']  # Added 113 for social housing
    
    print("Building cadastre database from CSV files...")
    for csv_file in tqdm(csv_files, desc="Reading CSV files"):
        print(f"  Processing: {csv_file}")
        df = read_csv_chunk(csv_file, cadastre_column)
        
        if df.empty:
            print(f"    → No data found (missing cadastre column or empty)")
            continue
        
        print(f"    → Found {len(df)} rows with cadastre numbers")
        
        # Process each row
        rows_added = 0
        for _, row in df.iterrows():
            cadastre_nr = normalize_cadastre(row[cadastre_column])
            
            # Skip if cadastre number is empty or invalid
            if not cadastre_nr:
                continue

            if allowed_cadastres and cadastre_nr not in allowed_cadastres:
                filtered_by_historical += 1
                continue
            
            # Convert row to dictionary
            row_dict = row.to_dict()
            
            # Check if this is a residential building FIRST
            is_residential = False
            match_keyword = None
            match_field = None
            building_use = str(row_dict.get('BuildingBasicData.BuildingUseKind.BuildingUseKindName', '')).lower()
            building_kind = str(row_dict.get('BuildingTypeData.BuildingKind.BuildingKindName', '')).lower()
            building_kind_id = str(row_dict.get('BuildingTypeData.BuildingKind.BuildingKindId', ''))

            # Check text stems
            for stem in residential_text_stems:
                if stem in building_use:
                    is_residential = True
                    match_keyword = stem
                    match_field = 'BuildingUseKindName'
                    break
                if stem in building_kind:
                    is_residential = True
                    match_keyword = stem
                    match_field = 'BuildingKindName'
                    break
            # Check ID prefixes if not already matched
            if not is_residential and building_kind_id:
                for pref in residential_id_prefixes:
                    if building_kind_id.startswith(pref):
                        is_residential = True
                        match_keyword = pref
                        match_field = 'BuildingKindId'
                        break
            
            # Only process residential buildings
            if not is_residential:
                continue
            
            # Filter columns by keywords (match against the stem - last part after the last dot)
            filtered_dict = {}
            for k, v in row_dict.items():
                if pd.notna(v):
                    # Extract the stem (last part after the last dot)
                    stem = k.split('.')[-1] if '.' in k else k
                    # Check if stem exactly matches any keyword
                    if stem in keywords or any(
                        marker in k.lower() for marker in ('address', 'adrese')
                    ):
                        filtered_dict[k] = v
            
            # Store the residential building (even if no matching keyword fields)
            # This ensures we capture ALL residential buildings
            if cadastre_nr not in cadastre_db:
                cadastre_db[cadastre_nr] = []
                rows_added += 1
            
            # Always include residential markers and native fields
            filtered_dict['_is_residential'] = True
            filtered_dict['_residential_match_keyword'] = match_keyword or ''
            filtered_dict['_residential_match_field'] = match_field or ''
            filtered_dict['_building_use_native'] = row_dict.get('BuildingBasicData.BuildingUseKind.BuildingUseKindName', '')
            filtered_dict['_building_kind_native'] = row_dict.get('BuildingTypeData.BuildingKind.BuildingKindName', '')
            filtered_dict['_building_kind_id_native'] = row_dict.get('BuildingTypeData.BuildingKind.BuildingKindId', '')

            cadastre_db[cadastre_nr].append(filtered_dict if filtered_dict else {'_is_residential': True})
        
        print(f"    → Added {rows_added} new cadastre numbers to database")
    
    print(f"Database complete: {len(cadastre_db)} unique cadastre numbers")
    if allowed_cadastres:
        print(f"  Filtered by historical lookup before database build: {filtered_by_historical}")
    return cadastre_db


def find_geojson_files(base_folder: str) -> List[str]:
    """Find all GeoJSON files in the base folder."""
    pattern = os.path.join(base_folder, "**", "*.geojson")
    files = glob.glob(pattern, recursive=True)
    for f in files:
        print(f"  Found GeoJSON: {f}")
    return files


def find_shapefiles(base_folder: str, layer_name: str = "KKBuilding") -> List[str]:
    """Find all shapefiles with the specified layer name."""
    pattern = os.path.join(base_folder, "**", f"{layer_name}.shp")
    files = glob.glob(pattern, recursive=True)
    for f in files:
        print(f"  Found shapefile: {f}")
    return files


def merge_building_data_to_geojson(geojson_path: str, cadastre_db: Dict[str, Dict[str, Any]], 
                                   output_path: str, debug: bool = False,
                                   allowed_cadastres: Optional[Set[str]] = None,
                                   address_lookup: Optional[Dict[str, str]] = None) -> Tuple[int, int, int]:
    """Merge building data into GeoJSON features based on cadastre numbers."""
    try:
        # Read GeoJSON
        with open(geojson_path, 'r', encoding='utf-8') as f:
            geojson_data = json.load(f)
        
        # Track statistics
        matched = 0
        not_matched = 0
        filtered_out = 0
        merged_features = []
        
        # Get sample property names from first feature for debugging
        sample_properties = None
        sample_code_values = []
        if geojson_data.get('features'):
            sample_properties = list(geojson_data['features'][0].get('properties', {}).keys())
            if debug:
                print(f"  Properties in GeoJSON: {sample_properties}")
                # Show sample CODE values
                for i, feature in enumerate(geojson_data['features'][:3]):
                    code = feature.get('properties', {}).get('CODE')
                    if code:
                        sample_code_values.append(code)
                if sample_code_values:
                    print(f"  Sample CODE values: {sample_code_values}")
                    print(f"  Sample cadastre numbers: {list(cadastre_db.keys())[:5]}")
        
        # Process each feature
        for feature_idx, feature in enumerate(geojson_data.get('features', [])):
            properties = feature.get('properties', {})
            
            # Try different property names that might contain the cadastre number
            code = None
            possible_properties = ['CODE', 'code', 'kod', 'KOD', 'KADASTRALNR', 'kadastralnr', 'cadastre_nr', 'cadastre', 'ID', 'OBJECTCODE']
            
            for prop_name in possible_properties:
                if prop_name in properties:
                    code = properties[prop_name]
                    if code:
                        break
            
            if not code:
                if debug and feature_idx == 0:
                    print(f"  WARNING: No cadastre number property found in feature. Available properties: {list(properties.keys())}")
                not_matched += 1
                continue
            
            # Format cadastre number to match CSV format
            code_str = str(code).strip()
            code_norm = normalize_cadastre(code_str)

            if code_norm not in allowed_cadastres:
                filtered_out += 1
                continue
            
            # Try different formats (preserve leading zeros for area codes)
            possible_keys = [
                code_str,
                code_str.zfill(14),  # Pad to 14 digits with leading zeros
            ]
            
            building_data = None
            for key in possible_keys:
                if key in cadastre_db:
                    building_data = cadastre_db[key]
                    break
            
            if building_data:
                matched += 1
                # Add building data to feature properties
                properties['building_data'] = building_data
                properties['ADDRESS'] = (address_lookup or {}).get(code_norm, '')
                
                # Flatten some key fields to top level for easier access
                first_building = building_data[0]
                properties['building_count'] = len(building_data)
                
                # Try to find relevant fields from the filtered data
                material_kind_name = None
                building_use_name = None
                building_kind_name = None
                
                for key in first_building.keys():
                    if (
                        'address' in key.lower() or 'adrese' in key.lower()
                    ) and first_building.get(key):
                        properties['ADDRESS'] = first_building.get(key)
                    if 'MaterialKindName' in key:
                        material_kind_name = first_building.get(key, '')
                        properties['building_material'] = material_kind_name
                    if 'BuildingUseKindName' in key:
                        building_use_name = first_building.get(key, '')
                        properties['building_use'] = building_use_name
                    if 'BuildingKindName' in key:
                        building_kind_name = first_building.get(key, '')
                        properties['building_kind'] = building_kind_name
                    if 'BuildingKindId' in key:
                        properties['building_kind_id'] = first_building.get(key, '')
                    if 'Area' in key and 'building_area' not in properties:
                        properties['building_area'] = first_building.get(key, '')

                    properties.setdefault('ADDRESS', '')
                
                # Preserve native classification fields and match details
                properties['is_residential'] = bool(first_building.get('_is_residential', True))
                properties['residential_match_keyword'] = first_building.get('_residential_match_keyword', '')
                properties['residential_match_field'] = first_building.get('_residential_match_field', '')
                properties['building_use_native'] = first_building.get('_building_use_native', '')
                properties['building_kind_native'] = first_building.get('_building_kind_native', '')
                properties['building_kind_id_native'] = first_building.get('_building_kind_id_native', '')
                
                # Classify material and add heavy_light classification
                if material_kind_name:
                    overall, heavy, light, unknown, details = classify_building_materials(material_kind_name)
                    properties['heavy_light'] = overall.value
                else:
                    properties['heavy_light'] = 'unknown'
            else:
                not_matched += 1

            merged_features.append(feature)

        geojson_data['features'] = merged_features
        
        # Save merged GeoJSON
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(geojson_data, f, ensure_ascii=False, indent=2)
        
        print(f"  Processed: {matched} matched, {not_matched} not matched, {filtered_out} filtered out by historical list")
        return matched, not_matched, filtered_out
        
    except Exception as e:
        print(f"Error processing {geojson_path}: {e}")
        import traceback
        traceback.print_exc()
        return 0, 0, 0


def convert_shapefile_to_geojson(shapefile_path: str) -> str:
    """Convert shapefile to GeoJSON and return the GeoJSON path."""
    try:
        gdf = gpd.read_file(shapefile_path)
        
        # Create output path
        base_name = os.path.basename(shapefile_path).replace('.shp', '.geojson')
        dir_name = os.path.dirname(shapefile_path)
        output_path = os.path.join(dir_name, base_name)
        
        # Save as GeoJSON
        gdf.to_file(output_path, driver='GeoJSON')
        return output_path
    except Exception as e:
        print(f"Error converting {shapefile_path}: {e}")
        return None


def main():
    """Main execution function."""
    print("=" * 80)
    print("Cadastre Data Merger")
    print("=" * 80)
    
    # Step 1: Find all CSV files
    print("\nStep 1: Finding CSV files...")
    csv_files = find_all_csv_files(BUILDING_BASE)
    print(f"Found {len(csv_files)} CSV files")
    
    # Step 2: Build cadastre database
    print("\nStep 2: Building cadastre database...")
    allowed_cadastres, address_lookup = load_historical_cadastres(HISTORICAL_CADASTRES_CSV)
    print(f"Loaded historical cadastre allowlist: {len(allowed_cadastres)} codes")
    print(f"Loaded addresses: {len(address_lookup)}")

    cadastre_db = build_cadastre_database(csv_files, allowed_cadastres=allowed_cadastres)
    
    # Step 3: Find GeoJSON files
    print("\nStep 3: Finding GeoJSON files...")
    geojson_files = find_geojson_files(SHAPEFILE_BASE)
    print(f"Found {len(geojson_files)} GeoJSON files")
    
    # Step 4: Find and convert shapefiles if no GeoJSON found
    if not geojson_files:
        print("\nNo GeoJSON files found. Looking for shapefiles to convert...")
        shapefiles = find_shapefiles(SHAPEFILE_BASE, "KKBuilding")
        print(f"Found {len(shapefiles)} KKBuilding shapefiles")
        
        if shapefiles:
            print("\nConverting shapefiles to GeoJSON...")
            for shapefile in tqdm(shapefiles, desc="Converting shapefiles"):
                print(f"  Converting: {shapefile}")
                geojson_path = convert_shapefile_to_geojson(shapefile)
                if geojson_path:
                    print(f"    → Saved to: {geojson_path}")
                    geojson_files.append(geojson_path)
                else:
                    print(f"    → ERROR: Conversion failed")
        else:
            print("  ERROR: No shapefiles found to convert!")
    
    if not geojson_files:
        print("\nERROR: No GeoJSON files to process. Exiting.")
        return
    
    # Step 5: Merge data
    print(f"\nStep 4: Merging building data into {len(geojson_files)} GeoJSON files...")
    total_matched = 0
    total_not_matched = 0
    total_filtered_out = 0
    
    for idx, geojson_file in enumerate(tqdm(geojson_files, desc="Processing GeoJSON files")):
        # Include the source group so each output file remains distinct.
        geojson_filename = os.path.basename(geojson_file).replace('.geojson', '')
        source_group = os.path.basename(os.path.dirname(geojson_file))
        
        output_filename = f"merged_{source_group}_{geojson_filename}.geojson"
        output_path = os.path.join(OUTPUT_BASE, output_filename)
        
        # Ensure output directory exists
        os.makedirs(OUTPUT_BASE, exist_ok=True)
        
        print(f"  Processing [{idx+1}/{len(geojson_files)}]: {geojson_file}")
        print(f"    → Output: {output_path}")
        
        # Enable debug mode for first file to see property names
        debug_mode = (idx == 0)
        
        # Merge data
        matched, not_matched, filtered_out = merge_building_data_to_geojson(
            geojson_file,
            cadastre_db,
            output_path,
            debug=debug_mode,
            allowed_cadastres=allowed_cadastres,
            address_lookup=address_lookup,
        )
        total_matched += matched
        total_not_matched += not_matched
        total_filtered_out += filtered_out
        print(f"    → Complete")
    
    # Final statistics
    print("\n" + "=" * 80)
    print("Summary:")
    print(f"  Total features matched: {total_matched}")
    print(f"  Total features not matched: {total_not_matched}")
    print(f"  Total features filtered out by historical list: {total_filtered_out}")
    
    total_features = total_matched + total_not_matched + total_filtered_out
    if total_features > 0:
        print(f"  Match rate: {total_matched / total_features * 100:.2f}%")
    else:
        print("  Match rate: N/A (no features processed)")
    
    print(f"\nOutput files saved to: {OUTPUT_BASE}")
    print("=" * 80)


if __name__ == "__main__":
    main()
