from pathlib import Path

APPROVED_SPECIALTIES = {"cardiology"}
ROOT = Path(__file__).parent


def rules(specialty: str) -> str:
    if specialty != "general" and specialty not in APPROVED_SPECIALTIES:
        raise ValueError("Specialty is not approved")
    return (ROOT / specialty / "rules.txt").read_text()

# Labels only. Planned specialties are NOT added to APPROVED_SPECIALTIES.
SPECIALTY_LABELS = {
    "general": ("الصحة العامة", "general health", "el se7a el 3amma"),
    "cardiology": ("القلب", "cardiology", "el 2alb"),
    "dermatology": ("الجلدية", "dermatology", "el geldeya"),
    "pediatrics": ("الأطفال", "pediatrics", "el atfal"),
    "orthopedics": ("العظام", "orthopedics", "el 3edam"),
    "ophthalmology": ("العيون", "ophthalmology", "el 3eyoun"),
    "obgyn": ("النسا والتوليد", "obstetrics and gynecology", "el nesa w el tawleed"),
    "ent": ("الأنف والأذن", "ENT", "el anf w el wedn"),
    "internal_medicine": ("الباطنة", "internal medicine", "el batna"),
    "dentistry": ("الأسنان", "dentistry", "el asnan"),
}


def specialty_label(key: str, lang: str) -> str:
    labels = SPECIALTY_LABELS.get(key)
    return labels[("ar", "en", "franco").index(lang)] if labels else key
