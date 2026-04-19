"""
synonyms.py — Drug name normalization layer
Handles India ↔ US name differences + common abbreviations + composition parsing
"""

import re

# ── India ↔ US / WHO INN synonym map ─────────────────────────────────────────
# Key   = what Indian doctors / datasets write
# Value = WHO INN / openFDA searchable name
SYNONYM_MAP = {
    # Pain / fever
    "paracetamol":              "acetaminophen",
    "pcm":                      "acetaminophen",
    "para":                     "acetaminophen",
    "crocin":                   "acetaminophen",
    "dolo":                     "acetaminophen",

    # NSAIDs
    "brufen":                   "ibuprofen",
    "combiflam":                "ibuprofen",
    "diclofenac sodium":        "diclofenac",
    "diclofenac potassium":     "diclofenac",
    "voveran":                  "diclofenac",

    # Antibiotics
    "amoxycillin":              "amoxicillin",
    "amox":                     "amoxicillin",
    "augmentin":                "amoxicillin",  # main salt
    "azithral":                 "azithromycin",
    "zithromax":                "azithromycin",
    "azee":                     "azithromycin",
    "ciprofloxacin hcl":        "ciprofloxacin",
    "cifran":                   "ciprofloxacin",
    "levofloxacin hemihydrate": "levofloxacin",
    "levaquin":                 "levofloxacin",
    "cefixime trihydrate":      "cefixime",
    "taxim":                    "cefixime",
    "cefpodoxime proxetil":     "cefpodoxime",
    "doxycycline hyclate":      "doxycycline",
    "vibramycin":               "doxycycline",

    # Diabetes
    "glycomet":                 "metformin",
    "glucophage":               "metformin",
    "metformin hcl":            "metformin",
    "metformin hydrochloride":  "metformin",
    "glibenclamide":            "glyburide",
    "daonil":                   "glyburide",
    "glipizide":                "glipizide",
    "glucotrol":                "glipizide",
    "sitagliptin phosphate":    "sitagliptin",
    "januvia":                  "sitagliptin",
    "vildagliptin":             "vildagliptin",
    "galvus":                   "vildagliptin",

    # Cholesterol
    "atorva":                   "atorvastatin",
    "lipitor":                  "atorvastatin",
    "storvas":                  "atorvastatin",
    "atorvastatin calcium":     "atorvastatin",
    "rosuvastatin calcium":     "rosuvastatin",
    "crestor":                  "rosuvastatin",
    "rozavel":                  "rosuvastatin",
    "simvastatin":              "simvastatin",
    "zocor":                    "simvastatin",

    # BP / heart
    "amlopres":                 "amlodipine",
    "stamlo":                   "amlodipine",
    "amlodac":                  "amlodipine",
    "amlodipine besylate":      "amlodipine",
    "telmisartan":              "telmisartan",
    "telma":                    "telmisartan",
    "losar":                    "losartan",
    "repace":                   "losartan",
    "losartan potassium":       "losartan",
    "enalapril maleate":        "enalapril",
    "enalapril":                "enalapril",
    "ramipril":                 "ramipril",
    "cardace":                  "ramipril",
    "metoprolol succinate":     "metoprolol",
    "metoprolol tartrate":      "metoprolol",
    "betaloc":                  "metoprolol",
    "atenolol":                 "atenolol",
    "tenormin":                 "atenolol",
    "bisoprolol fumarate":      "bisoprolol",
    "carvedilol":               "carvedilol",
    "coreg":                    "carvedilol",

    # Thyroid
    "thyroxine":                "levothyroxine",
    "eltroxin":                 "levothyroxine",
    "thyronorm":                "levothyroxine",
    "levothyroxine sodium":     "levothyroxine",

    # Stomach / GI
    "omez":                     "omeprazole",
    "ocid":                     "omeprazole",
    "pan":                      "pantoprazole",
    "pantocid":                 "pantoprazole",
    "pantop":                   "pantoprazole",
    "pantoprazole sodium":      "pantoprazole",
    "rabeprazole sodium":       "rabeprazole",
    "razo":                     "rabeprazole",
    "esomeprazole magnesium":   "esomeprazole",
    "nexium":                   "esomeprazole",
    "domperidone":              "domperidone",
    "domstal":                  "domperidone",
    "ondansetron hcl":          "ondansetron",
    "emeset":                   "ondansetron",
    "metoclopramide":           "metoclopramide",
    "perinorm":                 "metoclopramide",

    # Allergy / respiratory
    "cetirizine hcl":           "cetirizine",
    "cetzine":                  "cetirizine",
    "alerid":                   "cetirizine",
    "okacet":                   "cetirizine",
    "fexofenadine hcl":         "fexofenadine",
    "allegra":                  "fexofenadine",
    "loratadine":               "loratadine",
    "claritin":                 "loratadine",
    "levocetirizine dihydrochloride": "levocetirizine",
    "levocet":                  "levocetirizine",
    "montair":                  "montelukast",
    "singulair":                "montelukast",
    "montelukast sodium":       "montelukast",
    "salbutamol":               "albuterol",
    "asthalin":                 "albuterol",
    "budesonide":               "budesonide",
    "formoterol fumarate":      "formoterol",

    # Vitamins / supplements
    "vitamin b complex":        "vitamin b",
    "b complex":                "vitamin b",
    "becosules":                "vitamin b",
    "cyanocobalamin":           "vitamin b12",
    "methylcobalamin":          "methylcobalamin",
    "mecobalamin":              "methylcobalamin",
    "neurobion":                "vitamin b12",
    "folic acid":               "folic acid",
    "folate":                   "folic acid",
    "cholecalciferol":          "vitamin d3",
    "vitamin d3":               "vitamin d3",
    "calcitriol":               "calcitriol",
    "calcium carbonate":        "calcium",
    "shelcal":                  "calcium",
    "ascorbic acid":            "vitamin c",
    "vitamin c":                "vitamin c",

    # Pain / nerve
    "pregabalin":               "pregabalin",
    "lyrica":                   "pregabalin",
    "pregalin":                 "pregabalin",
    "gabapentin":               "gabapentin",
    "neurontin":                "gabapentin",
    "tramadol hcl":             "tramadol",
    "tramazac":                 "tramadol",

    # Mental health
    "alprazolam":               "alprazolam",
    "xanax":                    "alprazolam",
    "restyl":                   "alprazolam",
    "clonazepam":               "clonazepam",
    "lonazep":                  "clonazepam",
    "escitalopram oxalate":     "escitalopram",
    "nexito":                   "escitalopram",
    "cipralex":                 "escitalopram",
    "sertraline hcl":           "sertraline",
    "zoloft":                   "sertraline",
    "serta":                    "sertraline",
    "fluoxetine hcl":           "fluoxetine",
    "prozac":                   "fluoxetine",
    "fludac":                   "fluoxetine",

    # Blood thinners
    "clopidogrel bisulphate":   "clopidogrel",
    "clopidogrel bisulfate":    "clopidogrel",
    "plavix":                   "clopidogrel",
    "deplatt":                  "clopidogrel",
    "warfarin sodium":          "warfarin",
    "aspirin":                  "aspirin",
    "ecosprin":                 "aspirin",

    # ORS / electrolytes
    "oral rehydration salts":   "ors",
    "electral":                 "ors",
    "enerzal":                  "ors",

    # Steroids
    "prednisolone":             "prednisolone",
    "wysolone":                 "prednisolone",
    "dexamethasone sodium phosphate": "dexamethasone",
    "dexona":                   "dexamethasone",
    "methylprednisolone":       "methylprednisolone",
    "medrol":                   "methylprednisolone",

    # Antifungal
    "fluconazole":              "fluconazole",
    "forcan":                   "fluconazole",
    "itraconazole":             "itraconazole",
    "canditral":                "itraconazole",

    # Urology
    "tamsulosin hcl":           "tamsulosin",
    "urimax":                   "tamsulosin",
    "sildenafil citrate":       "sildenafil",
    "tadalafil":                "tadalafil",
    "tadacip":                  "tadalafil",
}

# ── Composition parser ────────────────────────────────────────────────────────
# Handles: "Paracetamol (500mg) + Caffeine (30mg)"
# Returns: ["paracetamol", "caffeine"]

_SPLIT_PATTERN = re.compile(r"[+/,&]|\band\b", re.IGNORECASE)
_DOSAGE_PATTERN = re.compile(
    r"\(?\d+\.?\d*\s*(?:mg|mcg|iu|ml|g|%|units?|meq|mmol)\)?",
    re.IGNORECASE,
)

def parse_composition(composition_str: str) -> list[str]:
    """
    Parse a composition string into individual normalized salt names.

    Examples:
      "Paracetamol (500mg) + Caffeine (30mg)"  → ["acetaminophen", "caffeine"]
      "Amoxycillin 500mg / Clavulanic Acid 125mg" → ["amoxicillin", "clavulanic acid"]
      "Metformin HCl (500mg)"                  → ["metformin"]
    """
    if not composition_str or not isinstance(composition_str, str):
        return []

    parts = _SPLIT_PATTERN.split(composition_str)
    result = []

    for part in parts:
        # Strip dosage numbers and units
        clean = _DOSAGE_PATTERN.sub("", part)
        # Strip parentheses, extra whitespace
        clean = re.sub(r"[()]", "", clean).strip().lower()
        # Remove trailing/leading punctuation
        clean = clean.strip(".,;:-")

        if len(clean) < 2:
            continue

        normalized = normalize(clean)
        if normalized and normalized not in result:
            result.append(normalized)

    return result


def normalize(drug_name: str) -> str:
    """
    Normalize a drug name:
    1. Lowercase + strip
    2. Remove dosage info e.g. "Metformin 500mg" → "metformin"
    3. Map via synonym dict
    """
    if not drug_name:
        return ""

    name = drug_name.lower().strip()

    # Strip dosage suffix e.g. "500mg", "10 mg", "0.5%"
    name = _DOSAGE_PATTERN.sub("", name).strip()
    name = name.strip(".,;:-()").strip()

    # Synonym lookup (exact)
    if name in SYNONYM_MAP:
        return SYNONYM_MAP[name]

    # Synonym lookup (partial — handles "metformin hcl 500" → "metformin")
    for key, val in SYNONYM_MAP.items():
        if name.startswith(key):
            return val
        if key.startswith(name) and len(name) >= 5:
            return val

    return name


def normalize_for_search(drug_name: str) -> str:
    """
    Returns the best search term for Netmeds —
    keeps Indian name (not US synonym) since Netmeds is Indian.
    Just strips dosage and cleans up.
    """
    if not drug_name:
        return ""
    name = drug_name.lower().strip()
    name = _DOSAGE_PATTERN.sub("", name).strip()
    name = name.strip(".,;:-()").strip()
    # Don't apply US synonym map for Netmeds search
    return name.title()


if __name__ == "__main__":
    # Quick test
    tests = [
        "Paracetamol",
        "Paracetamol 500mg",
        "Amoxycillin 500mg + Clavulanic Acid 125mg",
        "Metformin HCl",
        "Atorvastatin Calcium 10mg",
        "Vitamin B Complex",
        "PCM",
        "Dolo 650",
    ]
    print("Normalization tests:")
    for t in tests:
        print(f"  {t:45s} → normalize: {normalize(t)}")
    print()

    composition_tests = [
        "Paracetamol (500mg) + Caffeine (30mg)",
        "Amoxycillin 500mg/Clavulanic Acid 125mg",
        "Metformin HCl (500mg)",
        "Ibuprofen 400mg + Paracetamol 325mg",
    ]
    print("Composition parse tests:")
    for t in composition_tests:
        print(f"  {t:50s} → {parse_composition(t)}")
        