from datetime import date, datetime

import pytest

from nowa.clock import CAIRO
from nowa.messaging.templates import DoctorNames, render, render_emergency

GOLDENS = {
    ("1", "ar"): (
        "كريم محمود: حجزك مع د. هشام مصطفى الثلاثاء 6/10، رقمك 7، معادك حوالي 8:20 "
        "وممكن يتأخر. هنبعتلك امتى تتحرك. التفاصيل والعنوان: "
        "http://127.0.0.1:8000/l/x تليفون العيادة 01000000000"
    ),
    ("1", "en"): (
        "كريم محمود: your booking with Dr. Hesham Mostafa on Tue 6/10 is confirmed. "
        "Your number is 7, your time is around 8:20 and may move later. "
        "We'll text you when to leave. Details & address: "
        "http://127.0.0.1:8000/l/x Clinic: 01000000000"
    ),
    ("1", "franco"): (
        "كريم محمود: 7agzak ma3 Dr. Hesham Mostafa Tue 6/10, rakmak 7, "
        "ma3adak 7awaly 8:20 w momken yet2akhar. Hanb3atlak emta tet7arrak. "
        "El tafaseel wel 3enwan: http://127.0.0.1:8000/l/x "
        "Telephone el 3eyada 01000000000"
    ),
    ("2", "ar"): (
        "كريم محمود: اتحرك دلوقتي لعيادة د. هشام مصطفى، دورك قرب (رقم 7). "
        "لما تتحرك اضغط هنا: http://127.0.0.1:8000/w/x للاستفسار 01000000000"
    ),
    ("2", "en"): (
        "كريم محمود: leave now for Dr. Hesham Mostafa's clinic, your turn (number 7) "
        "is close. When you leave, tap here: http://127.0.0.1:8000/w/x "
        "Questions: 01000000000"
    ),
    ("2", "franco"): (
        "كريم محمود: et7arrak dilwa2ty le 3eyadet Dr. Hesham Mostafa, "
        "dorak korrab (rakm 7). Lama tet7arrak edghat hena: "
        "http://127.0.0.1:8000/w/x lel estefsar 01000000000"
    ),
    ("3", "ar"): (
        "كريم محمود: اتلغى حجزك مع د. هشام مصطفى يوم الثلاثاء 6/10 (رقم 7). "
        "لو مش إنت اللي لغيته كلم العيادة 01000000000"
    ),
    ("3", "en"): (
        "كريم محمود: your booking with Dr. Hesham Mostafa on Tue 6/10 (number 7) "
        "is cancelled. If you didn't cancel it, call the clinic: 01000000000"
    ),
    ("3", "franco"): (
        "كريم محمود: et2alagha 7agzak ma3 Dr. Hesham Mostafa yom Tue 6/10 "
        "(rakm 7). Law mesh enta elly laghetoh kallem el 3eyada 01000000000"
    ),
    ("4", "ar"): (
        "كريم محمود: د. هشام مصطفى اعتذر عن عيادة النهارده، وحجزك (رقم 7) اتلغى. "
        "احجز أقرب يوم فاضي من هنا: http://127.0.0.1:8000/r/x للاستفسار 01000000000"
    ),
    ("4", "en"): (
        "كريم محمود: Dr. Hesham Mostafa apologises, tonight's clinic is cancelled "
        "and your booking (number 7) is cancelled. Book the nearest free day here: "
        "http://127.0.0.1:8000/r/x Questions: 01000000000"
    ),
    ("4", "franco"): (
        "كريم محمود: Dr. Hesham Mostafa e3tazar 3an 3eyadet el naharda, "
        "w 7agzak (rakm 7) et2alagha. E7gez akrab yom fady men hena: "
        "http://127.0.0.1:8000/r/x lel estefsar 01000000000"
    ),
    ("5", "ar"): (
        'د. هشام مصطفى، العيادة المفروض تبدأ 8:20 ولسه ما دوستش "في الطريق". '
        "عندك 18 حجز النهارده. إنت في الطريق؟"
    ),
    ("5", "en"): (
        "Dr. Hesham Mostafa, the clinic was due to start at 8:20 and you haven't "
        'tapped "on my way" yet. You have 18 bookings tonight. Are you on your way?'
    ),
    ("6", "ar"): """📋 تقرير عيادة النهارده (الثلاثاء 6/10)

👥 الحجوزات: 18
✅ جم: 16
❌ ما جوش: 2 (A, B)
🚶 من غير حجز: 1

⏰ وصلت 8:20 (العيادة 8:20)
⏱️ متوسط الكشف: 15 دقيقة
⌛ متوسط انتظار المريض: حوالي 21 دقيقة

📩 مريض ما وصلتلوش الرسالة: C
🩺 المرضى سألوا 4 أسئلة صحية والـ AI رد عليها [اعرض]

📅 الخميس 8/10: 7 حجوزات لحد دلوقتي""",
    ("6", "en"): """📋 Tonight's clinic report (Tue 6/10)

👥 Bookings: 18
✅ Came: 16
❌ Didn't come: 2 (A, B)
🚶 Walk-ins: 1

⏰ You arrived 8:20 (clinic start 8:20)
⏱️ Average visit: 15 min
⌛ Average patient wait: about 21 min

📩 Patients whose message failed: C
🩺 Patients asked 4 health questions, answered by the AI [View]

📅 Thu 8/10: 7 bookings so far""",
}


@pytest.mark.parametrize("template,lang", list(GOLDENS))
def test_template_golden(template, lang):
    now = datetime(2026, 10, 6, 20, 20, tzinfo=CAIRO)
    common = dict(
        patient_name="كريم محمود",
        doctor_name=DoctorNames("هشام مصطفى", "Hesham Mostafa"),
        queue_number=7,
        clinic_phone="01000000000",
    )
    day = {"day_franco" if lang == "franco" else "day": date(2026, 10, 6)}
    if template == "1":
        blanks = common | day | dict(expected_time=now, link="/l/x")
    elif template == "2":
        blanks = common | dict(on_my_way_link="/w/x")
    elif template == "3":
        blanks = common | day
    elif template == "4":
        blanks = common | dict(rebook_link="/r/x")
    elif template == "5":
        blanks = dict(doctor_name=common["doctor_name"], clinic_start=now, booked_count=18)
    else:
        blanks = dict(
            day_date=date(2026, 10, 6),
            booked=18,
            came=16,
            no_show_count=2,
            no_show_names="A, B",
            walk_ins=1,
            doctor_arrival=now,
            clinic_start=now,
            avg_visit=15,
            avg_wait=21,
            failed_names="C",
            health_q_count=4,
            next_day=date(2026, 10, 8),
            next_day_bookings=7,
        )
    assert render(template, lang, blanks) == GOLDENS[template, lang]


EMERGENCY_GOLDENS = {
    ("general", "ar"): (
        "⚠️ اللي بتوصفه ممكن يكون حالة طوارئ ومينفعش يستنى معاد العيادة. "
        "اتصل بالإسعاف 123 دلوقتي، أو روح أقرب طوارئ فورًا. "
        "متسوقش بنفسك لو تعبان، وخلي حد معاك."
    ),
    ("general", "en"): (
        "⚠️ What you describe may be an emergency and should not wait for a clinic "
        "visit. Call the ambulance on 123 now, or go to the nearest emergency "
        "room right away. Don't drive yourself if you feel unwell; "
        "have someone with you."
    ),
    ("general", "franco"): (
        "⚠️ elly enta bet2olo momken yeb2a 7alet tawari2 w mayenfa3sh "
        "yestanna me3ad el 3eyada. Ettesel bel es3af 123 dlwa2ty, aw rou7 "
        "a2rab tawari2 fawran. Matsou2sh be nafsak law ta3ban, "
        "w khally 7ad ma3ak."
    ),
    ("eye_chemical", "ar"): (
        "⚠️ اغسل عينك دلوقتي بمية حنفية نضيفة كتير لمدة 15 لـ 20 دقيقة "
        "وإنت فاتح الجفن، وشيل العدسات لو لابسها. بعد الغسيل على طول "
        "روح أقرب طوارئ رمد. متأجلش الغسيل عشان تنزل بدري."
    ),
    ("eye_chemical", "en"): (
        "⚠️ Rinse your eye now with plenty of clean tap water for 15 to 20 "
        "minutes, holding the eyelids open, and take out contact lenses. "
        "Right after rinsing, go to the nearest eye emergency. "
        "Don't skip the rinse to leave sooner."
    ),
    ("eye", "ar"): (
        "⚠️ ده ممكن يكون طوارئ عين ومينفعش يستنى. روح أقرب طوارئ رمد "
        "(مستشفى رمد) دلوقتي، أو اتصل بـ 123."
    ),
    ("eye", "en"): (
        "⚠️ This may be an eye emergency and should not wait. "
        "Go to the nearest eye hospital emergency now, or call 123."
    ),
    ("filler", "ar"): (
        "⚠️ كلم الدكتور اللي حقنلك الفيلر دلوقتي حالًا. لو ما ردش خلال دقايق، "
        "روح أقرب طوارئ. لو نظرك اتأثر، روح الطوارئ فورًا أو اتصل بـ 123 "
        "من غير ما تستنى حد."
    ),
    ("filler", "en"): (
        "⚠️ Call the doctor who injected your filler right now. If they don't answer "
        "within minutes, go to the nearest emergency room. If your vision is "
        "affected, go to the emergency room or call 123 immediately, "
        "without waiting for anyone."
    ),
    ("labour", "ar"): (
        "⚠️ روحوا دلوقتي المستشفى اللي ناويين تولدوا فيها، أو أقرب طوارئ ولادة. "
        "لو مش قادرين تتحركوا اتصلوا بـ 123."
    ),
    ("labour", "en"): (
        "⚠️ Go now to the hospital where you plan to deliver, or the nearest "
        "maternity emergency. If you can't travel, call 123."
    ),
}


@pytest.mark.parametrize("kind,lang", list(EMERGENCY_GOLDENS))
def test_emergency_golden(kind, lang):
    assert render_emergency(kind, lang) == EMERGENCY_GOLDENS[kind, lang]


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_report_without_failed_names(lang):
    now = datetime(2026, 10, 6, 20, 20, tzinfo=CAIRO)
    blanks = dict(
        day_date=date(2026, 10, 6),
        booked=18,
        came=16,
        no_show_count=2,
        no_show_names="A, B",
        walk_ins=1,
        doctor_arrival=now,
        clinic_start=now,
        avg_visit=15,
        avg_wait=21,
        failed_names=[],
        health_q_count=4,
        next_day=date(2026, 10, 8),
        next_day_bookings=7,
    )
    expected = "\n".join(
        line for line in GOLDENS["6", lang].split("\n") if not line.startswith("📩")
    )
    assert render("6", lang, blanks) == expected
    assert blanks["failed_names"] == []
    del blanks["failed_names"]
    with pytest.raises(ValueError):
        render("6", lang, blanks)
