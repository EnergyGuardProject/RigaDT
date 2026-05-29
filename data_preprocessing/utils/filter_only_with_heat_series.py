import argparse
import json
from pathlib import Path
from typing import Any, Dict


def has_heat_series(props: Dict[str, Any]) -> bool:
    ts = props.get("heat_consumption_timeseries")
    return isinstance(ts, dict) and len(ts) > 0


def resolve_input_path(raw_input: str, script_dir: Path) -> Path:
    p = Path(raw_input)
    if p.exists():
        return p

    # Try from project root when invoked from inside script_pipeline.
    project_root = script_dir.parent.parent
    alt = project_root / raw_input
    if alt.exists():
        return alt

    # Common fallback names in script_pipeline.
    candidates = [
        script_dir.parent / "output" / "historical_residential_buildings_full_pipeline_heat_energy.json",
        script_dir.parent / "output" / "all_buildings_with_building_fields_heat.json",
        script_dir.parent / "historical_residential_buildings_full_pipeline_heat_energy.json",
        script_dir.parent / "all_buildings_with_heat_energy.json",
        script_dir.parent / "all_buildings_with_building_fields_heat_energy.json",
    ]
    for c in candidates:
        if c.exists():
            return c

    return p


def resolve_output_path(raw_output: str, script_dir: Path) -> Path:
    p = Path(raw_output)
    if p.is_absolute():
        return p

    # If user runs from DT-EFI root with default script_pipeline/... keep it as-is.
    if str(p).startswith("script_pipeline/") or str(p).startswith("script_pipeline\\"):
        return p

    # Default relative outputs go to script_pipeline for consistency.
    return script_dir.parent / p


def main() -> None:
    script_dir = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        description="Create a GeoJSON containing only features with non-empty heat series."
    )
    parser.add_argument(
        "--input",
        default="script_pipeline/output/historical_residential_buildings_full_pipeline_heat_energy.json",
        help="Input GeoJSON path",
    )
    parser.add_argument(
        "--output",
        default="script_pipeline/output/all_buildings_with_building_fields_heat_only_all_steps.json",
        help="Output GeoJSON path",
    )
    args = parser.parse_args()

    input_path = resolve_input_path(args.input, script_dir)
    output_path = resolve_output_path(args.output, script_dir)

    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    if not isinstance(features, list):
        raise ValueError("Invalid GeoJSON: features is not a list")

    filtered = []
    for feat in features:
        props = feat.get("properties", {})
        if has_heat_series(props):
            filtered.append(feat)

    output_data = dict(data)
    output_data["features"] = filtered

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    total = len(features)
    kept = len(filtered)
    dropped = total - kept
    pct = (kept / total * 100) if total else 0

    print("Done")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Total features: {total}")
    print(f"Kept (with heat series): {kept}")
    print(f"Dropped (without heat series): {dropped}")
    print(f"Kept percentage: {pct:.2f}%")


if __name__ == "__main__":
    main()
