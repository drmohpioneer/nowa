from datetime import time
from typing import Any

CLINIC: dict[str, Any] = {
    "clinic": {
        "slug": "dr-hesham",
        "name": "عيادة د. هشام مصطفى",
        "specialty": "cardiology",
        "address": "Heliopolis, Cairo",
        "lat": 30.0911,
        "lng": 31.3228,
        "phone": "01000000000",
        "max_per_evening": 30,
        "usual_visit_min": 15,
        "cushion_min": 10,
        "safe_drive_min": 45,
        "is_sandbox": False,
        "clock_offset_s": 0,
    },
    "doctor": {
        "name_ar": "هشام مصطفى",
        "name_en": "Hesham Mostafa",
        "mobile_e164": "+201000000001",
        "lang": "ar",
    },
    "hours": [{"weekday": day, "start": time(19), "end": time(23)} for day in (6, 1, 3)],
    "info": [
        {"key": "price", "text": "الكشف ٣٠٠ جنيه (سعر خيالي للعرض)"},
        {"key": "address", "text": "مصر الجديدة، القاهرة (عيادة خيالية للعرض)"},
        {"key": "what_to_bring", "text": "هات التحاليل والأشعات السابقة وقائمة أدويتك."},
    ],
    "learned_pace": {"mean_visit_min": 13.3, "n": 20},
    "learned_start_gap": {"mean_min": 8, "n": 10},
}
