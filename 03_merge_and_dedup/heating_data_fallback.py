import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Optional


def normalize_cadastre(value: Any) -> Optional[str]:
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


def parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip().replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(value: Any) -> Optional[int]:
    n = parse_float(value)
    if n is None:
        return None
    try:
        return int(round(n))
    except Exception:
        return None


def has_building_data(props: Dict[str, Any]) -> bool:
    bd = props.get("building_data")
    return isinstance(bd, list) and len(bd) > 0


def parse_kind(raw_kind: str) -> Dict[str, str]:
    text = (raw_kind or "").strip()
    if not text:
        return {"id": "", "name": ""}

    parts = text.split(" ", 1)
    maybe_id = "".join(ch for ch in parts[0] if ch.isdigit())
    if maybe_id and len(parts) > 1:
        return {"id": maybe_id, "name": parts[1].strip()}
    return {"id": "", "name": text}


def is_residential(kind_name: str, kind_id: str) -> bool:
    text = (kind_name or "").lower()
    stems = ["maja", "dzivojam", "dzivokl"]
    normalized = (
        text.replace("\u0101", "a")
        .replace("\u012b", "i")
        .replace("\u0113", "e")
        .replace("\u0146", "n")
        .replace("\u0137", "k")
        .replace("\u013c", "l")
        .replace("\u0161", "s")
        .replace("\u017e", "z")
    )
    if any(stem in normalized for stem in stems):
        return True
    return str(kind_id).startswith(("1110", "112", "113"))


def build_heating_lookup(csv_path: Path) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}

    with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            # Expected minimal columns:
            # 0 address, 1 cadastre, 2 kind, 3 year, 4 total area, 5 expedient area, 6 flats, 7 floors
            if len(row) < 8:
                continue

            cad = normalize_cadastre(row[1])
            if not cad:
                continue

            kind = parse_kind(row[2])
            rec = {
                "source_address": (row[0] or "").strip(),
                "kind_id": kind["id"],
                "kind_name": kind["name"],
                "manufacture_year": parse_int(row[3]),
                "total_area": parse_float(row[4]),
                "expedient_area": parse_float(row[5]),
                "flat_count": parse_int(row[6]),
                "floors": parse_int(row[7]),
                "raw_kind": (row[2] or "").strip(),
            }

            # Prefer rows with floors over rows without floors.
            if cad not in lookup:
                lookup[cad] = rec
            elif lookup[cad].get("floors") is None and rec.get("floors") is not None:
                lookup[cad] = rec

    return lookup


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill missing building_data from Heating_2017-2024.csv fallback source."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input GeoJSON path",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output GeoJSON path",
    )
    parser.add_argument(
        "--heating-csv",
        default="./Heating_2017-2024.csv",
        help="Path to Heating_2017-2024.csv",
    )
    parser.add_argument(
        "--cadastre-field",
        default="CODE",
        help="Feature property that contains cadastre code",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    heating_csv_path = Path(args.heating_csv)

    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")
    if not heating_csv_path.exists():
        raise FileNotFoundError(f"Heating CSV not found: {heating_csv_path}")

    print(f"Loading fallback CSV: {heating_csv_path}")
    lookup = build_heating_lookup(heating_csv_path)
    print(f"Fallback cadastre keys: {len(lookup)}")

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    if not isinstance(features, list):
        raise ValueError("Invalid GeoJSON: features is not a list")

    missing_before = 0
    filled = 0
    still_missing = 0
    no_cadastre = 0

    for feat in features:
        props = feat.setdefault("properties", {})
        if has_building_data(props):
            continue

        missing_before += 1
        cad = normalize_cadastre(props.get(args.cadastre_field))
        if not cad:
            no_cadastre += 1
            still_missing += 1
            continue

        rec = lookup.get(cad)
        if not rec:
            still_missing += 1
            continue

        floors = rec.get("floors")
        if floors is None:
            still_missing += 1
            continue

        kind_name = rec.get("kind_name") or ""
        kind_id = rec.get("kind_id") or ""
        raw_kind = rec.get("raw_kind") or ""
        total_area = rec.get("total_area")
        expedient_area = rec.get("expedient_area")
        flat_count = rec.get("flat_count")
        year = rec.get("manufacture_year")

        # Use the best available area value for flattened fields.
        area_value = total_area if total_area is not None else expedient_area

        # Use the kind text as the closest available proxy for the native use field.
        use_name = kind_name or raw_kind

        fallback_row: Dict[str, Any] = {
            "BuildingBasicData.BuildingGroundFloors": floors,
            "BuildingTypeData.BuildingKind.BuildingKindName": kind_name,
            "BuildingTypeData.BuildingKind.BuildingKindId": kind_id,
            "BuildingBasicData.BuildingUseKind.BuildingUseKindName": use_name,
            "_is_residential": is_residential(kind_name, kind_id),
            "_residential_match_keyword": "heating_fallback",
            "_residential_match_field": "Heating_2017-2024.csv",
            "_building_use_native": use_name,
            "_building_kind_native": kind_name,
            "_building_kind_id_native": kind_id,
            "_source_csv_file": heating_csv_path.name,
            "_fallback_source": "Heating_2017-2024.csv",
        }

        if total_area is not None:
            fallback_row["BuildingOrPremiseGroupExplicationData.TotalArea"] = total_area
        if expedient_area is not None:
            fallback_row[
                "BuildingOrPremiseGroupExplicationData.TotalAreaDetails.ExpedientArea"
            ] = expedient_area
        if flat_count is not None:
            fallback_row["BuildingBasicData.BuildingPregCount"] = flat_count
        if area_value is not None:
            fallback_row["BuildingBasicData.BuildingArea"] = area_value

        props["building_data"] = [fallback_row]
        props["building_count"] = 1
        if use_name:
            props["building_use"] = use_name
            props["building_use_native"] = use_name
        props["building_kind"] = kind_name
        props["building_kind_id"] = kind_id
        if area_value is not None:
            props["building_area"] = area_value
        props["is_residential"] = fallback_row["_is_residential"]
        props["residential_match_keyword"] = "heating_fallback"
        props["residential_match_field"] = "Heating_2017-2024.csv"
        props["building_kind_native"] = kind_name
        props["building_kind_id_native"] = kind_id
        props["heavy_light"] = "unknown"
        props["source_csv_file"] = heating_csv_path.name
        props["building_data_source"] = "heating_fallback"

        if year is not None and props.get("manufacture_year") in (None, ""):
            props["manufacture_year"] = year

        filled += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("Done")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Features: {len(features)}")
    print(f"Missing building_data before: {missing_before}")
    print(f"Filled from fallback: {filled}")
    print(f"Still missing building_data: {still_missing}")
    print(f"Missing cadastre among missing building_data: {no_cadastre}")


if __name__ == "__main__":
    main()
