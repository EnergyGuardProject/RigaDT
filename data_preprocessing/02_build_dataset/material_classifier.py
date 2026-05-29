import json
import os
from pathlib import Path
from enum import Enum

class MaterialWeight(Enum):
    HEAVY = "heavy"
    LIGHT = "light"
    MIXED = "mixed"
    UNKNOWN = "unknown"

# Material classification dictionary
MATERIAL_CLASSIFICATION = {
    # Heavy materials
    "Dzelzsbetona": MaterialWeight.HEAVY,
    "Dzelzsbetons": MaterialWeight.HEAVY,
    "Dzelzsbetona": MaterialWeight.HEAVY,
    "dzelzsbetona": MaterialWeight.HEAVY,
    "dzelzsbetons": MaterialWeight.HEAVY,
    "Betona": MaterialWeight.HEAVY,
    "betona": MaterialWeight.HEAVY,
    "Betons": MaterialWeight.HEAVY,
    "betons": MaterialWeight.HEAVY,
    "Ķieģeļu": MaterialWeight.HEAVY,
    "ķieģeļu": MaterialWeight.HEAVY,
    "ķieģeļa": MaterialWeight.HEAVY,
    "Akmens": MaterialWeight.HEAVY,
    "akmens": MaterialWeight.HEAVY,
    "Metāla": MaterialWeight.HEAVY,
    "metāla": MaterialWeight.HEAVY,
    "Metāls": MaterialWeight.HEAVY,
    "metāls": MaterialWeight.HEAVY,
    "Tērauda": MaterialWeight.HEAVY,
    "tērauda": MaterialWeight.HEAVY,
    "Mūra": MaterialWeight.HEAVY,
    "mūra": MaterialWeight.HEAVY,
    "Mūris": MaterialWeight.HEAVY,
    "mūris": MaterialWeight.HEAVY,
    "Azbestcementa": MaterialWeight.HEAVY,
    "azbestcementa": MaterialWeight.HEAVY,
    "Keramzītbetona": MaterialWeight.HEAVY,
    "keramzītbetona": MaterialWeight.HEAVY,
    "Skaidbetona": MaterialWeight.HEAVY,
    "skaidbetona": MaterialWeight.HEAVY,
    "Ģipšbetona": MaterialWeight.HEAVY,
    "ģipšbetona": MaterialWeight.HEAVY,
    "Vieglbetona": MaterialWeight.HEAVY,  # Contains "betons" but "vieglbetona" is lighter
    "Monolīta": MaterialWeight.HEAVY,
    "Monolītais": MaterialWeight.HEAVY,
    "Monolītā": MaterialWeight.HEAVY,
    "monolītais": MaterialWeight.HEAVY,
    
    # Light materials
    "Koka": MaterialWeight.LIGHT,
    "koka": MaterialWeight.LIGHT,
    "Koks": MaterialWeight.LIGHT,
    "koks": MaterialWeight.LIGHT,
    "Arbolīta": MaterialWeight.LIGHT,
    "arbolīta": MaterialWeight.LIGHT,
    "Gāzbetona": MaterialWeight.LIGHT,
    "gāzbetona": MaterialWeight.LIGHT,
    "Polimēru": MaterialWeight.LIGHT,
    "polimēru": MaterialWeight.LIGHT,
    "Stikla": MaterialWeight.LIGHT,
    "stikla": MaterialWeight.LIGHT,
    "Bituma": MaterialWeight.LIGHT,
    "bituma": MaterialWeight.LIGHT,
    "Bitumena": MaterialWeight.LIGHT,
    "bitumena": MaterialWeight.LIGHT,
    "Ruberoīds": MaterialWeight.LIGHT,
    "ruberoīds": MaterialWeight.LIGHT,
    "Plēve": MaterialWeight.LIGHT,
    "plēve": MaterialWeight.LIGHT,
    "Krāsojums": MaterialWeight.LIGHT,
    "krāsojums": MaterialWeight.LIGHT,
    "Apmetums": MaterialWeight.LIGHT,
    "apmetums": MaterialWeight.LIGHT,
    "Sintētisko": MaterialWeight.LIGHT,
    "sintētisko": MaterialWeight.LIGHT,
    "Keramikas": MaterialWeight.LIGHT,
    "keramikas": MaterialWeight.LIGHT,
}

def classify_material(material_name):
    """Classify a single material as heavy or light"""
    if not material_name:
        return MaterialWeight.UNKNOWN
    
    # Check direct match first
    if material_name in MATERIAL_CLASSIFICATION:
        return MATERIAL_CLASSIFICATION[material_name]
    
    # Check if material contains keywords
    material_lower = material_name.lower()
    
    # Check for heavy material keywords
    heavy_keywords = ["dzelzsbetons", "betona", "betons", "ķieģelis", "ķieģeļ", "akmens", 
                      "metāl", "tēraud", "mūr", "azbest", "cement", "keramz", "skaidbeton",
                      "alumīnij", "māla", "vara", "misiņ", "slānekl", "fibrocementa", "šķiedrcementa"]
    for keyword in heavy_keywords:
        if keyword in material_lower:
            return MaterialWeight.HEAVY
    
    # Check for light material keywords
    light_keywords = ["koka", "koks", "arbolīt", "gāzbetons", "polimēru", "stikl", "bitum",
                      "ruberoīd", "plēv", "krāsojum", "apmetum", "sintétisk", "kokšķiedru"]
    for keyword in light_keywords:
        if keyword in material_lower:
            return MaterialWeight.LIGHT
    
    return MaterialWeight.UNKNOWN

def classify_building_materials(material_kind_name_str):
    """
    Classify building materials from MaterialKindName string
    Returns: (classification, heavy_count, light_count, mixed_count, unknown_count, details)
    """
    if not material_kind_name_str:
        return MaterialWeight.UNKNOWN, 0, 0, 0, 0, []
    
    # Split by pipe (multiple materials separated by |)
    materials = material_kind_name_str.split('|')
    
    heavy_count = 0
    light_count = 0
    unknown_count = 0
    details = []
    
    for material in materials:
        material = material.strip()
        if not material:
            continue
        
        classification = classify_material(material)
        details.append((material, classification.value))
        
        if classification == MaterialWeight.HEAVY:
            heavy_count += 1
        elif classification == MaterialWeight.LIGHT:
            light_count += 1
        else:
            unknown_count += 1
    
    # Determine overall classification
    if heavy_count > 0 and light_count == 0:
        overall = MaterialWeight.HEAVY
    elif light_count > 0 and heavy_count == 0:
        overall = MaterialWeight.LIGHT
    elif heavy_count > 0 and light_count > 0:
        overall = MaterialWeight.MIXED
    else:
        overall = MaterialWeight.UNKNOWN
    
    return overall, heavy_count, light_count, unknown_count, details

# Example usage
if __name__ == "__main__":
    # Interactive mode - enter material names to classify
    print("Material Weight Classifier")
    print("=" * 80)
    print("Enter material names to classify as heavy or light.")
    print("Type 'quit' to exit.\n")
    
    while True:
        material_input = input("Enter material name: ").strip()
        
        if material_input.lower() == 'quit':
            break
        
        if not material_input:
            continue
        
        overall, heavy, light, unknown, details = classify_building_materials(material_input)
        
        print(f"\nResult: {overall.value.upper()}")
        print(f"Heavy materials: {heavy}, Light materials: {light}, Unknown: {unknown}")
        
        if details:
            print("Details:")
            for mat, classification in details:
                print(f"  - {mat}: {classification}")
        print()
