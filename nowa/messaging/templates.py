from dataclasses import dataclass
from datetime import date, datetime, timedelta
from string import Formatter
from typing import Any

from nowa.clock import CAIRO
from nowa.config import get_settings


@dataclass(frozen=True)
class DoctorNames:
    name_ar: str
    name_en: str | None


@dataclass(frozen=True)
class Rendered:
    text: str
    approved: bool


TEMPLATES: dict[tuple[str, str], str] = {
    (
        "1",
        "ar",
    ): (
        "{patient_name}: حجزك مع د. {doctor_name} {day}، رقمك "
        "{queue_number}، معادك حوالي {expected_time} وممكن يتأخر. هنبعتلك "
        "امتى تتحرك. التفاصيل والعنوان: {link} تليفون العيادة "
        "{clinic_phone}"
    ),
    (
        "2",
        "ar",
    ): (
        "{patient_name}: اتحرك دلوقتي لعيادة د. {doctor_name}، دورك قرب "
        "(رقم {queue_number}). لما تتحرك اضغط هنا: {on_my_way_link} "
        "للاستفسار {clinic_phone}"
    ),
    (
        "3",
        "ar",
    ): (
        "{patient_name}: اتلغى حجزك مع د. {doctor_name} يوم {day} (رقم "
        "{queue_number}). لو مش إنت اللي لغيته كلم العيادة {clinic_phone}"
    ),
    (
        "4",
        "ar",
    ): (
        "{patient_name}: د. {doctor_name} اعتذر عن عيادة النهارده، وحجزك "
        "(رقم {queue_number}) اتلغى. احجز أقرب يوم فاضي من هنا: "
        "{rebook_link} للاستفسار {clinic_phone}"
    ),
    (
        "5",
        "ar",
    ): (
        "د. {doctor_name}، العيادة المفروض تبدأ {clinic_start} ولسه ما "
        'دوستش "في الطريق". عندك {booked_count} حجز النهارده. إنت في '
        "الطريق؟"
    ),
    (
        "6",
        "ar",
    ): (
        "📋 تقرير عيادة النهارده ({day_date})\n\n👥 الحجوزات: {booked}\n✅ جم: "
        "{came}\n❌ ما جوش: {no_show_count} ({no_show_names})\n🚶 من غير حجز: "
        "{walk_ins}\n\n⏰ وصلت {doctor_arrival} (العيادة {clinic_start})\n⏱️ "
        "متوسط الكشف: {avg_visit} دقيقة\n⌛ متوسط انتظار المريض: حوالي "
        "{avg_wait} دقيقة\n\n📩 مريض ما وصلتلوش الرسالة: {failed_names}\n🩺 "
        "المرضى سألوا {health_q_count} أسئلة صحية والـ AI رد عليها "
        "[اعرض]\n\n📅 {next_day}: {next_day_bookings} حجوزات لحد دلوقتي"
    ),
    (
        "1",
        "en",
    ): (
        "{patient_name}: your booking with Dr. {doctor_name} on {day} is "
        "confirmed. Your number is {queue_number}, your time is around "
        "{expected_time} and may move later. We'll text you when to "
        "leave. Details & address: {link} Clinic: {clinic_phone}"
    ),
    (
        "1",
        "franco",
    ): (
        "{patient_name}: 7agzak ma3 Dr. {doctor_name} {day_franco}, "
        "rakmak {queue_number}, ma3adak 7awaly {expected_time} w momken "
        "yet2akhar. Hanb3atlak emta tet7arrak. El tafaseel wel 3enwan: "
        "{link} Telephone el 3eyada {clinic_phone}"
    ),
    (
        "2",
        "en",
    ): (
        "{patient_name}: leave now for Dr. {doctor_name}'s clinic, your "
        "turn (number {queue_number}) is close. When you leave, tap here: "
        "{on_my_way_link} Questions: {clinic_phone}"
    ),
    (
        "2",
        "franco",
    ): (
        "{patient_name}: et7arrak dilwa2ty le 3eyadet Dr. {doctor_name}, "
        "dorak korrab (rakm {queue_number}). Lama tet7arrak edghat hena: "
        "{on_my_way_link} lel estefsar {clinic_phone}"
    ),
    (
        "3",
        "en",
    ): (
        "{patient_name}: your booking with Dr. {doctor_name} on {day} "
        "(number {queue_number}) is cancelled. If you didn't cancel it, "
        "call the clinic: {clinic_phone}"
    ),
    (
        "3",
        "franco",
    ): (
        "{patient_name}: et2alagha 7agzak ma3 Dr. {doctor_name} yom "
        "{day_franco} (rakm {queue_number}). Law mesh enta elly laghetoh "
        "kallem el 3eyada {clinic_phone}"
    ),
    (
        "4",
        "en",
    ): (
        "{patient_name}: Dr. {doctor_name} apologises, tonight's clinic "
        "is cancelled and your booking (number {queue_number}) is "
        "cancelled. Book the nearest free day here: {rebook_link} "
        "Questions: {clinic_phone}"
    ),
    (
        "4",
        "franco",
    ): (
        "{patient_name}: Dr. {doctor_name} e3tazar 3an 3eyadet el "
        "naharda, w 7agzak (rakm {queue_number}) et2alagha. E7gez akrab "
        "yom fady men hena: {rebook_link} lel estefsar {clinic_phone}"
    ),
    (
        "5",
        "en",
    ): (
        "Dr. {doctor_name}, the clinic was due to start at {clinic_start} "
        'and you haven\'t tapped "on my way" yet. You have {booked_count} '
        "bookings tonight. Are you on your way?"
    ),
    (
        "6",
        "en",
    ): (
        "📋 Tonight's clinic report ({day_date})\n\n👥 Bookings: {booked}\n✅ "
        "Came: {came}\n❌ Didn't come: {no_show_count} ({no_show_names})\n🚶 "
        "Walk-ins: {walk_ins}\n\n⏰ You arrived {doctor_arrival} (clinic "
        "start {clinic_start})\n⏱️ Average visit: {avg_visit} min\n⌛ "
        "Average patient wait: about {avg_wait} min\n\n📩 Patients whose "
        "message failed: {failed_names}\n🩺 Patients asked {health_q_count} "
        "health questions, answered by the AI [View]\n\n📅 {next_day}: "
        "{next_day_bookings} bookings so far"
    ),
}

OPERATIONAL: dict[str, dict[str, Any]] = {
    "question_card": {
        "texts": {"ar": 'سؤال {n} من {total}: "{text}"', "en": 'Question {n} of {total}: "{text}"'},
        "status": "APPROVED",
    },
    "question_card_count": {
        "texts": {"ar": "(سأل عنه {count} مرضى)", "en": "(asked by {count} patients)"},
        "status": "APPROVED",
    },
    "doctor_alert_unreachable": {
        "texts": {
            "ar": "ما قدرناش نوصل رسالة لـ {patient_name} (رقم {queue_number})، كلمه على {phone}",
            "en": (
                "We couldn't deliver a message to {patient_name} (number "
                "{queue_number}). Call them on {phone}."
            ),
        },
        "status": "APPROVED",
    },
    "doctor_alert_brake": {
        "texts": {
            "ar": (
                "وقف إرسال رسايل {channel_label} النهارده بعد {count} رسالة، في "
                "حاجة غلط. راجع اللوحة."
            ),
            "en": (
                "{channel_label} messages stopped for tonight after {count} "
                "messages, something's wrong. Check the dashboard."
            ),
        },
        "status": "APPROVED",
    },
    "reset_code": {
        "texts": {
            "ar": "كود إعادة التعيين: {code}. صالح 10 دقايق. لو مش إنت تجاهل الرسالة.",
            "en": (
                "Your Nowa password reset code: {code}. Valid for 10 minutes. If "
                "this wasn't you, ignore this message."
            ),
        },
        "status": "APPROVED",
    },
    "signup_code": {
        "texts": {
            "ar": "كود تفعيل حسابك في نوا: {code}. صالح 10 دقايق.",
            "en": "Your Nowa sign-up code: {code}. Valid for 10 minutes.",
        },
        "status": "APPROVED",
    },
    "secretary_link": {
        "texts": {
            "ar": (
                "دي لينك تنبيهات عيادة د. {doctor_name} على تليجرام. ابعتيها "
                "لمراسلتك على تليجرام وافتحيها: {secretary_link}"
            )
        },
        "status": "APPROVED",
    },
    "secretary_linked": {
        "texts": {"ar": "اتفعل! هتوصلك تنبيهات لو رسالة لمريض من عيادة د. {doctor_name} ما وصلتش."},
        "status": "APPROVED",
    },
    "secretary_unlinked": {
        "texts": {
            "ar": (
                "اتوقفت تنبيهات عيادة د. {doctor_name} عندك. لو الدكتور حب يفعلها "
                "تاني هيبعتلك لينك جديد."
            )
        },
        "status": "APPROVED",
    },
    "doctor_linked": {
        "texts": {
            "ar": (
                "اتفعل بوت نوا لعيادة د. {doctor_name}. من هنا هتوصلك تنبيهات "
                "الليلة وتقرير آخر اليوم."
            ),
            "en": (
                "Nowa's bot is now linked to Dr. {doctor_name}'s clinic. You'll "
                "get tonight's alerts and the evening report here."
            ),
        },
        "status": "APPROVED",
    },
    "patient_linked": {
        "texts": {
            "ar": "اتفعل! هتوصلك تنبيهات حجوزاتك على الرقم اللي ينتهي بـ {last_4}.",
            "en": "Linked! You'll get updates on your bookings for the number ending in {last_4}.",
            ("franco"): (
                "Et3amel el link! Hayewsalak updates 3ala 7agzak lel ra2m elly by5las be {last_4}."
            ),
        },
        "status": "APPROVED",
    },
    "bookings_header": {
        "texts": {"ar": "حجوزاتك:", "en": "Your bookings:", "franco": "7agzatak:"},
        "status": "APPROVED",
    },
    "bookings_line": {
        "texts": {
            "ar": (
                "د. {doctor_name}، {day}، رقمك {queue_number}، معادك حوالي "
                "{expected_time}، {status_label}"
            ),
            "en": (
                "Dr. {doctor_name}, {day}, your number {queue_number}, around "
                "{expected_time}, {status_label}"
            ),
            "franco": (
                "Dr. {doctor_name}, {day}, rakmak {queue_number}, 7awaly "
                "{expected_time}, {status_label}"
            ),
        },
        "status": "APPROVED",
    },
    "bookings_empty": {
        "texts": {
            "ar": "مفيش حجوزات نشطة على الرقم ده دلوقتي.",
            "en": "No active bookings on this number right now.",
            "franco": "Mafeesh 7agzat nashta 3ala el ra2m da dlwa2ty.",
        },
        "status": "APPROVED",
    },
    "patient_unlinked": {
        "texts": {
            "ar": "اتوقفت الرسايل هنا. لو حبيت ترجع، افتح لينك حجزك من الرسالة اللي وصلتك.",
            "en": (
                "Messages stopped here. If you want them back, open your booking "
                "link from the SMS you got."
            ),
            "franco": (
                "Etwa2af el rasayel hena. Law 3ayez terga3, efta7 link 7agzak men "
                "el resala elly wasaltak."
            ),
        },
        "status": "APPROVED",
    },
    "just_filled": {
        "texts": {
            "ar": "للأسف آخر مكان في {day} اتحجز قبل ما نخلص. أقرب يوم فاضي: {next_day}. تحجزه؟",
            "en": (
                "The last place on {day} was just taken before we could finish. "
                "Nearest free day: {next_day}. Book it?"
            ),
            "franco": (
                "Le2asaf akher makan fe {day} et7agaz 2abl ma nekhallas. A2rab "
                "yom fady: {next_day}. Te7gezo?"
            ),
        },
        "status": "APPROVED",
    },
    "triage_urgent": {
        "texts": {
            "ar": "محتاج تتفحص النهارده أو بكرة، من غير ما تستنى معادك المحجوز.",
            "en": (
                "This needs to be seen today or tomorrow, you don't need to wait "
                "for your booked appointment."
            ),
            ("franco"): (
                "Da me7taag kashf elnaharda aw bokra, min gheir ma testanna el me3ad elly 7agazto."
            ),
        },
        "status": "APPROVED",
    },
    "triage_unclear": {
        "texts": {
            "ar": "لو الأعراض شديدة اتصل بـ 123، أو اكتب لنا تاني.",
            "en": "If your symptoms are severe, call 123, or write to us again.",
            "franco": "Law el a3rad shadeeda ettesel be 123, aw ekteblena tany.",
        },
        "status": "APPROVED",
    },
    "health_no_answer": {
        "texts": {
            "ar": "السؤال ده هيوصل للدكتور نفسه، وهيرد عليك في أقرب فرصة.",
            "en": (
                "This question will go straight to the doctor, and he'll answer "
                "you as soon as he can."
            ),
            "franco": "El so2al da hayewsal lel doctor nafso, w hayrod 3alek fi a2rab forsa.",
        },
        "status": "APPROVED",
    },
    "out_of_specialty": {
        "texts": {
            ("ar"): (
                "السؤال ده خارج تخصص د. {doctor_name} ({specialty}). جرب تسأل دكتور في التخصص ده."
            ),
            "en": (
                "This is outside Dr. {doctor_name}'s specialty ({specialty}). "
                "Please ask a doctor in that specialty."
            ),
            "franco": (
                "El so2al da khareg takhasos Dr. {doctor_name} ({specialty}). "
                "Garrab tes2al doctor fel takhasos da."
            ),
        },
        "status": "APPROVED",
    },
    "phone_cap": {
        "texts": {
            "ar": "الرقم ده عليه ٣ حجوزات شغالة في العيادة. الغي واحد الأول وبعدين احجز.",
            "en": (
                "This phone already has 3 active bookings at this clinic. Cancel "
                "one first, then book."
            ),
            ("franco"): (
                "El ra2m da 3aleh 3 7agzat sha8ala fel 3eyada. El8y wa7ed el awel w ba3den e7gez."
            ),
        },
        "status": "APPROVED",
    },
}

EMERGENCY: dict[tuple[str, str], str] = {
    (
        "general",
        "ar",
    ): (
        "⚠️ اللي بتوصفه ممكن يكون حالة طوارئ ومينفعش يستنى معاد العيادة. "
        "اتصل بالإسعاف 123 دلوقتي، أو روح أقرب طوارئ فورًا. متسوقش بنفسك "
        "لو تعبان، وخلي حد معاك."
    ),
    (
        "general",
        "en",
    ): (
        "⚠️ What you describe may be an emergency and should not wait for "
        "a clinic visit. Call the ambulance on 123 now, or go to the "
        "nearest emergency room right away. Don't drive yourself if you "
        "feel unwell; have someone with you."
    ),
    (
        "general",
        "franco",
    ): (
        "⚠️ elly enta bet2olo momken yeb2a 7alet tawari2 w mayenfa3sh "
        "yestanna me3ad el 3eyada. Ettesel bel es3af 123 dlwa2ty, aw rou7 "
        "a2rab tawari2 fawran. Matsou2sh be nafsak law ta3ban, w khally "
        "7ad ma3ak."
    ),
    (
        "eye_chemical",
        "ar",
    ): (
        "⚠️ اغسل عينك دلوقتي بمية حنفية نضيفة كتير لمدة 15 لـ 20 دقيقة "
        "وإنت فاتح الجفن، وشيل العدسات لو لابسها. بعد الغسيل على طول روح "
        "أقرب طوارئ رمد. متأجلش الغسيل عشان تنزل بدري."
    ),
    (
        "eye_chemical",
        "en",
    ): (
        "⚠️ Rinse your eye now with plenty of clean tap water for 15 to "
        "20 minutes, holding the eyelids open, and take out contact "
        "lenses. Right after rinsing, go to the nearest eye emergency. "
        "Don't skip the rinse to leave sooner."
    ),
    (
        "eye",
        "ar",
    ): (
        "⚠️ ده ممكن يكون طوارئ عين ومينفعش يستنى. روح أقرب طوارئ رمد "
        "(مستشفى رمد) دلوقتي، أو اتصل بـ 123."
    ),
    (
        "eye",
        "en",
    ): (
        "⚠️ This may be an eye emergency and should not wait. Go to the "
        "nearest eye hospital emergency now, or call 123."
    ),
    (
        "filler",
        "ar",
    ): (
        "⚠️ كلم الدكتور اللي حقنلك الفيلر دلوقتي حالًا. لو ما ردش خلال "
        "دقايق، روح أقرب طوارئ. لو نظرك اتأثر، روح الطوارئ فورًا أو اتصل "
        "بـ 123 من غير ما تستنى حد."
    ),
    (
        "filler",
        "en",
    ): (
        "⚠️ Call the doctor who injected your filler right now. If they "
        "don't answer within minutes, go to the nearest emergency room. "
        "If your vision is affected, go to the emergency room or call 123 "
        "immediately, without waiting for anyone."
    ),
    (
        "labour",
        "ar",
    ): (
        "⚠️ روحوا دلوقتي المستشفى اللي ناويين تولدوا فيها، أو أقرب طوارئ "
        "ولادة. لو مش قادرين تتحركوا اتصلوا بـ 123."
    ),
    (
        "labour",
        "en",
    ): (
        "⚠️ Go now to the hospital where you plan to deliver, or the "
        "nearest maternity emergency. If you can't travel, call 123."
    ),
}


AR_DAYS = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")
EN_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def format_day(d: date, lang: str) -> str:
    if lang not in {"ar", "en", "franco"} or not isinstance(d, date) or isinstance(d, datetime):
        raise ValueError("A date and supported language are required")
    days = AR_DAYS if lang == "ar" else EN_DAYS
    return f"{days[d.weekday()]} {d.day}/{d.month}"


def format_time(dt: datetime, lang: str) -> str:
    if lang not in {"ar", "en", "franco"} or not isinstance(dt, datetime) or dt.utcoffset() is None:
        raise ValueError("An aware datetime and supported language are required")
    local = dt.astimezone(CAIRO)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    rounded = start + timedelta(minutes=int((local - start).total_seconds() / 300 + 0.5) * 5)
    return f"{rounded.hour % 12 or 12}:{rounded.minute:02d}"


def _fill(text: str, lang: str, blanks: dict[str, Any]) -> str:
    fields = {field for _, field, _, _ in Formatter().parse(text) if field is not None}
    if fields != blanks.keys():
        raise ValueError("Missing or unknown template blank")
    values: dict[str, str] = {}
    for name, value in blanks.items():
        if value is None or value == "":
            raise ValueError(f"Empty blank: {name}")
        if name == "doctor_name":
            if not isinstance(value, DoctorNames):
                raise ValueError("doctor_name requires DoctorNames")
            value = value.name_ar if lang == "ar" else value.name_en
            if not value:
                raise ValueError("Missing doctor name in message language")
        elif name in {"day", "day_franco", "day_date", "next_day"}:
            value = format_day(value, lang)
        elif name in {"expected_time", "clinic_start", "doctor_arrival"}:
            value = format_time(value, lang)
        elif name == "link" or name.endswith(("_link", "_url")):
            if not isinstance(value, str) or not value.startswith("/"):
                raise ValueError("Link blanks require an absolute path")
            value = get_settings().public_base_url + value
        values[name] = str(value)
    return text.format_map(values)


def render(template_id: str, lang: str, blanks: dict[str, Any]) -> str:
    text = TEMPLATES[template_id, lang]
    if template_id == "6":
        fields = {field for _, field, _, _ in Formatter().parse(text) if field is not None}
        if fields != blanks.keys():
            raise ValueError("Missing or unknown template blank")
        blanks = dict(blanks)
        if blanks.get("no_show_count") == 0:
            text = text.replace(" ({no_show_names})", "")
            blanks.pop("no_show_names", None)
        omitted = {
            key
            for key in ("failed_names", "doctor_arrival", "avg_visit", "avg_wait", "health_q_count")
            if blanks.get(key) is None
            or blanks.get(key) == []
            or (key == "health_q_count" and blanks.get(key) == 0)
        }
        lines = text.split("\n")
        for key in omitted:
            removed = [line for line in lines if "{" + key + "}" in line]
            for line in removed:
                for _, field, _, _ in Formatter().parse(line):
                    if field is not None:
                        blanks.pop(field, None)
            lines = [line for line in lines if "{" + key + "}" not in line]
        compact: list[str] = []
        for line in lines:
            if line or not compact or compact[-1]:
                compact.append(line)
        text = "\n".join(compact)
        if blanks.get("next_day") is None:
            text = text.replace("{next_day}", "")
            blanks.pop("next_day", None)
            blanks["next_day_bookings"] = 0
    return _fill(text, lang, blanks)


def render_operational(key: str, lang: str, blanks: dict[str, Any]) -> Rendered:
    if key == "question_card":
        blanks = dict(blanks)
        count = blanks.pop("count", 1)
        body = _fill(OPERATIONAL[key]["texts"][lang], lang, blanks)
        if count > 1:
            body += " " + _fill(
                OPERATIONAL["question_card_count"]["texts"][lang], lang, {"count": count}
            )
        return Rendered(body, True)
    entry = OPERATIONAL[key]
    return Rendered(_fill(entry["texts"][lang], lang, blanks), entry["status"] == "APPROVED")


def render_emergency(kind: str | None, lang: str) -> str:
    if lang not in {"ar", "en", "franco"}:
        raise ValueError("Unsupported language")
    if kind not in {"general", "eye_chemical", "eye", "filler", "labour"}:
        kind = "general"
    if lang == "franco" and kind != "general":
        lang = "en"
    return EMERGENCY[kind, lang]
