#!/usr/bin/env python3
"""Convert State Land building XML exports to one flattened CSV file."""

import csv
import sys
from collections import OrderedDict
from pathlib import Path
import xml.etree.ElementTree as ET


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def text_value(element: ET.Element) -> str:
    return " ".join((element.text or "").split())


def flatten_item(item: ET.Element) -> dict[str, str]:
    values: OrderedDict[str, list[str]] = OrderedDict()

    def visit(element: ET.Element, path: list[str]) -> None:
        name = local_name(element.tag)
        current_path = path + [name]
        children = list(element)
        if not children:
            value = text_value(element)
            if value:
                key = ".".join(current_path[1:])
                values.setdefault(key, []).append(value)
            return
        for child in children:
            visit(child, current_path)

    visit(item, [])
    return {
        key: "|".join(dict.fromkeys(items))
        for key, items in values.items()
    }


def convert(folder: Path) -> Path:
    xml_files = sorted(folder.glob("*.xml"))
    if not xml_files:
        raise FileNotFoundError(f"No XML files found in {folder}")

    rows: list[dict[str, str]] = []
    for xml_file in xml_files:
        root = ET.parse(xml_file).getroot()
        items = [
            element
            for element in root.iter()
            if local_name(element.tag) == "BuildingItemData"
        ]
        rows.extend(flatten_item(item) for item in items)

    if not rows:
        raise ValueError(f"No BuildingItemData records found in {folder}")

    fieldnames = sorted({key for row in rows for key in row})
    output = folder / f"{folder.name}.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Converted {len(xml_files)} XML file(s), {len(rows)} building record(s): {output}")
    return output


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {Path(sys.argv[0]).name} <xml-folder>")
    convert(Path(sys.argv[1]).resolve())


if __name__ == "__main__":
    main()
