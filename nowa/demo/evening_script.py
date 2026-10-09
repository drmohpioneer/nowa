"""Fictional replay inputs, never a replacement for the timing engine."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Patient:
    number: int
    name: str
    name_en: str
    phone: str
    area: str
    lang: Literal["ar", "en", "franco"]
    reaction_min: int = 1


NAMES = (
    "Ahmed Ali",
    "Nour Hassan",
    "Youssef Adel",
    "Omar Samir",
    "Salma Ahmed",
    "Ali Nour",
    "Mahmoud Karim",
    "Hana Mostafa",
    "Mona Adel",
    "Farida Samir",
    "Laila Hassan",
    "Mostafa Ali",
    "Hossam Nour",
    "Dina Samir",
    "Tamer Hassan",
    "Amira Adel",
    "Heba Mostafa",
    "Samir Ahmed",
)
NAMES_AR = (
    "أحمد علي",
    "نور حسن",
    "يوسف عادل",
    "عمر سمير",
    "سلمى أحمد",
    "علي نور",
    "محمود كريم",
    "هنا مصطفى",
    "منى عادل",
    "فريدة سمير",
    "ليلى حسن",
    "مصطفى علي",
    "حسام نور",
    "دينا سمير",
    "تامر حسن",
    "أميرة عادل",
    "هبة مصطفى",
    "سمير أحمد",
)
PATIENTS = tuple(
    Patient(n, NAMES_AR[n - 1], name, f"+201000002{n:03d}", "Heliopolis", "ar")
    for n, name in enumerate(NAMES, 1)
)
KARIM = 7  # Karim Mahmoud books his father, Mahmoud Karim; consent is for another person.
SILENT = 11
NO_SHOW = 15
CANCEL = 12
CANCEL_MINUTE = 150
ON_WAY_MINUTE = 190
DOCTOR_AREA = "Dokki"
WALK_IN_AFTER = 9
VISIT_LENGTHS = (13, 12, 14, 13, 22, 12, 13, 14, 12, 13, 23, 12, 13, 14, 12, 13, 12, 13)
HEALTH_QUESTION = "هل دوا الضغط هفضل واخده طول عمري؟"
DOCTOR_QUESTION = "هل أجيب التحاليل القديمة معايا؟"


def validate() -> None:
    numbers = {p.number for p in PATIENTS}
    if len(PATIENTS) != 18 or len(numbers) != 18 or numbers != set(range(1, 19)):
        raise ValueError("Script needs 18 unique queue numbers")
    if not {KARIM, SILENT, NO_SHOW, CANCEL, WALK_IN_AFTER} <= numbers or CANCEL <= KARIM:
        raise ValueError("Invalid scripted patient reference")
    if len(VISIT_LENGTHS) != 18 or any(v <= 0 for v in VISIT_LENGTHS):
        raise ValueError("Invalid visit lengths")
