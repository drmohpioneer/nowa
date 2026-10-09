"""Deterministic reference-area aliases and typo tolerance; no model or network."""

import re
import unicodedata
from functools import lru_cache
from typing import Literal

from nowa.reference import AREAS


def normalize(text: str) -> str:
    text = text.casefold().translate(str.maketrans("أإآٱةى", "ااااهي", "ـ"))
    text = "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text)
    text = "".join(c for c in text if not unicodedata.category(c).startswith("M"))
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


ALIASES = (
    "مصر الجديدة|مصر الجديده|هليوبوليس|هليوبليس|Heliopolis|masr el gedida|masr elgedida",
    "مدينة نصر|مدينه نصر|Nasr City|madinet nasr|medinet nasr",
    "مدينتي|Madinaty|Madinati",
    "التجمع|تجمع|التجمع الخامس|تجمع خامس|القاهرة الجديدة|New Cairo|el tagamo3|tagamo3",
    "المعادي|معادي|معادى|Maadi|ma3adi|el ma3adi",
    "الزمالك|زمالك|Zamalek|el zamalek",
    "الدقي|دقي|Dokki|Doki|do22i|el do22i",
    "المهندسين|مهندسين|Mohandessin|mohandeseen|mohandessin|mohandseen",
    "شبرا|Shubra|shobra|شبرا مصر|shubra misr|shobra masr",
    "عين شمس|Ain Shams|3ein shams|ein shams",
    "العبور|عبور|El Obour|obour|el obor",
    "أكتوبر|اكتوبر|٦ أكتوبر|6th of October|october|6 October|ستة اكتوبر",
    "الرحاب|rehab|el re7ab",
    "التجمع الاول|tagamo3 el awal|el tagamo3 el awel",
    "التجمع الثالث|tagamo3 el talet|el tagamo3 el talet",
    "الشروق|shorouk|el shorou2",
    "بدر|badr|madinet badr",
    "العاصمة الإدارية|العاصمه|el 3asema|new capital",
    "المطرية|matareya|el matarya",
    "المرج|marg|el marg",
    "السلام|madinet el salam|el salam",
    "النزهة|nozha|el nozha",
    "شيراتون|sheraton|sheraton el matar",
    "جسر السويس|gesr el suez|gesr elsewis|gesr el sewes|gesr el swes",
    "الزيتون|zeitoun|el zaytoun",
    "روض الفرج|rod el farag|roud el farag",
    "الساحل|sahel|el sa7el",
    "وسط البلد|downtown|west el balad|wust el balad",
    "جاردن سيتي|garden city|garden seety",
    "عابدين|abdin|3abdeen",
    "السيدة زينب|sayeda zeinab|el sayeda zeinab",
    "مصر القديمة|masr el adima|masr el 2adima",
    "المنيل|manial|el manyal",
    "زهراء المعادي|zahraa el maadi|zahra el ma3adi",
    "دار السلام|dar el salam|dar elsalam",
    "حلوان|helwan|7elwan",
    "١٥ مايو|15 مايو|15 may|15 mayo|khomastashar mayo",
    "التبين|tebbin|el tebin",
    "المقطم|mokattam|mo2attam|el mo2atam",
    "القطامية|katameya|el 2atameya",
    "المعصرة|maasara|el ma3sara",
    "شبرا الخيمة|shobra el kheima|shubra el khema",
    "قليوب|qalyoub|2alyoub",
    "الخانكة|khanka|el khanka",
    "العجوزة|agouza|el 3agouza",
    "إمبابة|embaba|imbaba",
    "الوراق|warraq|el wara2",
    "بولاق الدكرور|boulaq el dakrour|bola2 el dakrour",
    "الجيزة|giza|el geeza",
    "الهرم|haram|el haram",
    "فيصل|faisal|faysal",
    "العمرانية|omraneya|el 3omraneya",
    "الشيخ زايد|zayed|el sheikh zayed",
    "حدائق أكتوبر|hadayek october|7adayek october",
    "حدائق الاهرام|hadayek el ahram|7adayek el ahram",
    "بولاق|بولاق ابو العلا|boulaq|bola2 abo el 3ela",
    "الزاوية الحمراء|zawya el hamra|el zawya el 7amra",
    "عزبة النخل|ezbet el nakhl|3ezbet el nakhl",
    "الدرب الاحمر|darb el ahmar|el darb el a7mar",
    "الخليفة|khalifa|el khaleefa",
    "دجلة المعادي|دجلة|degla|degla el ma3adi",
    "المعادي الجديدة|maadi el gedida|el ma3adi el gedida",
    "طرة|tora|tura",
    "المريوطية|مريوطية الهرم|mariouteya|el maryoteya",
    "كرداسة|kerdasa|kerdassa",
    "الحي العاشر مدينة نصر|el 7ay el 3asher madinet nasr|nasr city tenth district",
    "النهضة|نهضة السلام|nahda|el nahda",
    "العباسية|abbasiya|el 3abaseya",
    "غمرة|ghamra|ghamrah",
    "رمسيس|ramsis|ramsees",
    "مسطرد|mostorod|mostoroud",
    "بهتيم|bahtim|bahteem",
)


def ambiguous(text: str) -> bool:
    return normalize(text) in {
        "مدينه",
        "المدينه",
        "من المدينه",
        "من مدينه",
        "city",
        "from city",
        "the city",
        "from the city",
        "el madina",
        "men el madina",
    }


def damerau_levenshtein(left: str, right: str) -> int:
    """Edit distance including adjacent transpositions (unrestricted Damerau)."""
    ceiling = len(left) + len(right)
    distance = [[0] * (len(right) + 2) for _ in range(len(left) + 2)]
    distance[0][0] = ceiling
    for i in range(len(left) + 1):
        distance[i + 1][0], distance[i + 1][1] = ceiling, i
    for j in range(len(right) + 1):
        distance[0][j + 1], distance[1][j + 1] = ceiling, j
    seen: dict[str, int] = {}
    for i, a in enumerate(left, 1):
        last_match = 0
        for j, b in enumerate(right, 1):
            previous_i, previous_j = seen.get(b, 0), last_match
            cost = int(a != b)
            if not cost:
                last_match = j
            distance[i + 1][j + 1] = min(
                distance[i][j] + cost,
                distance[i + 1][j] + 1,
                distance[i][j + 1] + 1,
                distance[previous_i][previous_j] + i - previous_i + j - previous_j - 1,
            )
        seen[a] = i
    return distance[-1][-1]


@lru_cache(maxsize=1)
def _compiled_aliases(
    aliases: tuple[str, ...], reference: tuple[tuple[str, str, float, float], ...]
) -> tuple[tuple[int, str, re.Pattern[str]], ...]:
    values = [
        (index, normalize(alias))
        for index, group in enumerate(aliases, 1)
        for alias in [*group.split("|"), reference[index - 1][0], reference[index - 1][1]]
    ]
    return tuple(
        (index, alias, re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)"))
        for index, alias in values
    )


def _fuzzy_limit(alias: str) -> int:
    if re.search(r"[\u0600-\u06FF]", alias):
        return 1
    return 2 if len(alias) >= 5 else 1


def resolve(text: str) -> int | None | Literal["unknown"]:
    value = normalize(text)
    if (
        not value
        or ambiguous(text)
        or re.search(
            r"(?:ايه المناطق|ما هي المناطق|which areas|what (?:are the )?areas|eh el manate2)",
            value,
        )
    ):
        return "unknown"
    aliases = _compiled_aliases(ALIASES, tuple(AREAS))
    exact = [
        (index, match.start(), match.end())
        for index, _, pattern in aliases
        for match in pattern.finditer(value)
    ]
    # A district's longer name owns an embedded nickname; distinct places ask again.
    matches = {
        index
        for index, start, end in exact
        if not any(a <= start and end <= b and b - a > end - start for _, a, b in exact)
    }
    if matches:
        return next(iter(matches)) if len(matches) == 1 else "unknown"
    # Match a whole place phrase, never an arbitrary near-spelling in a health sentence.
    phrase = re.sub(r"^(?:i live in|coming from|from|men|ana men|انا من|جاي من|من)\s+", "", value)
    # Arabic names are short and dense (المنصورة is two edits from المعصرة), so Arabic
    # aliases allow one edit; Latin aliases allow two from five letters up (FIX 3 ruling).
    fuzzy = [
        (len(alias), index)
        for index, alias, _ in aliases
        if abs(len(phrase) - len(alias)) <= _fuzzy_limit(alias)
        and damerau_levenshtein(phrase, alias) <= _fuzzy_limit(alias)
    ]
    if not fuzzy:
        return None
    longest = max(length for length, _ in fuzzy)
    matches = {index for length, index in fuzzy if length == longest}
    return next(iter(matches)) if len(matches) == 1 else "unknown"
