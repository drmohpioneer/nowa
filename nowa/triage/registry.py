from pathlib import Path

APPROVED_SPECIALTIES = {"cardiology"}
ROOT = Path(__file__).parent


def rules(specialty: str) -> str:
    if specialty != "general" and specialty not in APPROVED_SPECIALTIES:
        raise ValueError("Specialty is not approved")
    return (ROOT / specialty / "rules.txt").read_text()
