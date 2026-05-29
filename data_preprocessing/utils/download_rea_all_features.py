import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


def fetch_json(url: str, params: dict, method: str = "GET") -> dict:
    if method.upper() == "POST":
        response = requests.post(url, data=params, timeout=60)
    else:
        response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"API error: {payload['error']}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Download all REA MapServer layer records into one JSON file.")
    parser.add_argument(
        "--base-url",
        default="https://georiga.lv/server/rest/services/REA/MapServer/0/query",
        help="ArcGIS layer query endpoint.",
    )
    parser.add_argument(
        "--out",
        default="./script_pipeline/output/rea_all_features.json",
        help="Output JSON file path.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="How many OBJECTIDs to request per call.",
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    count_payload = fetch_json(
        args.base_url,
        {
            "where": "1=1",
            "returnCountOnly": "true",
            "f": "json",
        },
    )
    total = int(count_payload.get("count", 0))

    ids_payload = fetch_json(
        args.base_url,
        {
            "where": "1=1",
            "returnIdsOnly": "true",
            "f": "json",
        },
    )

    object_ids = ids_payload.get("objectIds", []) or []
    object_id_field = ids_payload.get("objectIdFieldName", "OBJECTID")
    object_ids = sorted(int(object_id) for object_id in object_ids)

    features = []
    fields = None
    spatial_reference = None

    for index in range(0, len(object_ids), args.chunk_size):
        chunk = object_ids[index : index + args.chunk_size]
        chunk_ids = ",".join(str(object_id) for object_id in chunk)
        payload = fetch_json(
            args.base_url,
            {
                "objectIds": chunk_ids,
                "outFields": "*",
                "returnGeometry": "true",
                "f": "json",
            },
            method="POST",
        )

        chunk_features = payload.get("features", []) or []
        features.extend(chunk_features)

        if fields is None and isinstance(payload.get("fields"), list):
            fields = payload.get("fields")
        if spatial_reference is None and isinstance(payload.get("spatialReference"), dict):
            spatial_reference = payload.get("spatialReference")

        print(f"Fetched {len(features)}/{len(object_ids)} features")

    output = {
        "source": args.base_url,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "reported_count": total,
        "downloaded_count": len(features),
        "object_id_field": object_id_field,
        "fields": fields or [],
        "spatialReference": spatial_reference or {},
        "features": features,
    }

    with out_path.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False)

    print(f"Saved: {out_path}")
    print(f"reported_count={total}")
    print(f"downloaded_count={len(features)}")


if __name__ == "__main__":
    main()