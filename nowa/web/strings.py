# APPROVED under Decisions 048 and 050; UI wording is never send-gated.
STRINGS: dict[str, dict[str, str]] = {}


def _add(key: str, ar: str, en: str, franco: str) -> None:
    STRINGS["patient." + key] = {"ar": ar, "en": en, "franco": franco}


_add("brand", "نوا", "Nowa", "Nowa")
_add("title", "تفاصيل حجزك", "Your booking", "Tafaseel 7agzak")
_add("doctor", "الدكتور", "Doctor", "El doctor")
_add("day", "اليوم", "Day", "El yom")
_add("queue", "رقمك", "Your number", "Rakmak")
_add("expected", "المعاد المتوقع", "Expected time", "El ma3ad el motawakka3")
_add("state", "حالة الحجز", "Booking status", "7alet el 7agz")
_add("address", "عنوان العيادة", "Clinic address", "3enwan el 3eyada")
_add("phone", "تليفون العيادة", "Clinic phone", "Telephone el 3eyada")
_add("map", "افتح الخريطة", "Open map", "Efta7 el khareeta")
_add("cancel", "إلغاء الحجز", "Cancel booking", "Elgha el 7agz")
_add("change", "غيّر اليوم", "Change day", "Ghayyar el yom")
_add("rebook", "احجز يوم تاني", "Book another day", "E7gez yom tany")
_add(
    "open_telegram",
    "افتح تليجرام عشان توصلك الرسائل",
    "Open Telegram to get your messages",
    "Efta7 Telegram 3ashan tewsalak el rasayel",
)
_add("telegram", "اربط تليجرام", "Link my Telegram", "Erbot Telegram")
_add(
    "last4",
    "آخر ٤ أرقام من تليفون الحجز",
    "Last 4 digits of the booking phone",
    "Akher 4 arkam men telephone el 7agz",
)
_add("tap", "أنا في الطريق", "I'm on my way", "Ana fel tareek")
_add("undo", "لسه ما اتحركتش", "I haven't left yet", "Lessa ma et7arraktesh")
_add("done", "تمام، سجلنا إنك في الطريق", "Done, you're on your way", "Tamam, enta fel tareek")
_add(
    "new_link",
    "تمام، لينك حجزك الجديد هيوصلك على تليجرام",
    "Done, your new link will reach you on Telegram",
    "Tamam, link 7agzak el gedeed haywsalak 3ala Telegram",
)
_add(
    "cancelled_done",
    "تمام، حجزك اتلغى",
    "Done, your booking is cancelled",
    "Tamam, 7agzak et2alagha",
)
_add(
    "wait",
    "هنقولك على تليجرام امتى تتحرك",
    "We'll tell you on Telegram when to leave",
    "Han2ollak 3ala Telegram emta tet7arrak",
)
_add(
    "readonly",
    "الحجز ده مش متاح للتغيير. للاستفسار كلم العيادة",
    "This booking cannot be changed. Call the clinic with questions",
    "El 7agz da mesh mota7 lel taghyeer. Kallem el 3eyada",
)
_add(
    "verify_failed",
    "آخر ٤ أرقام مش مظبوطة. راجع رقم الموبايل اللي حجزت بيه.",
    "The last 4 digits did not match. Check the mobile number you booked with.",
    "Akher 4 arkam mesh mazboota. Rage3 rakam el mobile elly 7agazt beeh.",
)
_add(
    "locked",
    "محاولات كتير. جرّب بعد انتهاء ربع الساعة الحالية",
    "Too many attempts. Try after the current 15-minute window ends",
    "Mo7awalat keteer. Garrab ba3d rob3 el sa3a el 7aleya",
)
_add(
    "day_refused",
    "اليوم ده مش متاح، اختار يوم من الأيام المتاحة",
    "That day is unavailable. Choose an available day",
    "El yom da mesh mota7, ekhtar yom tany",
)
_add(
    "no_days",
    "مفيش أيام متاحة حاليًا، كلم العيادة",
    "No days available now. Call the clinic",
    "Mafeesh ayam mota7a delwa2ty, kallem el 3eyada",
)
_add("sandbox", "تليجرام مش متاح هنا", "Telegram is not available here", "Telegram mesh mota7 hena")
_add(
    "repeated",
    "لينك تليجرام اتفتح قبل كده",
    "The Telegram link was already opened",
    "Link Telegram etfata7 abl keda",
)
_add(
    "not_found",
    "اللينك مش متاح، كلم العيادة",
    "This link is unavailable. Call the clinic",
    "El link mesh mota7, kallem el 3eyada",
)
_add(
    "forbidden",
    "الطلب مش صالح. افتح اللينك من رسالة تليجرام تاني",
    "This request is invalid. Open the link in your Telegram message again",
    "Efta7 link el Telegram tany",
)
_add(
    "server_error",
    "حصلت مشكلة. جرّب تاني، ولو استمرت كلم العيادة",
    "Something went wrong. Try again, and call the clinic if it continues",
    "7asalet moshkela. Garrab tany, w law estamarret kallem el 3eyada",
)
_add("booked", "محجوز", "Booked", "Ma7gooz")
_add("told_to_leave", "اتحرك دلوقتي", "Leave now", "Et7arrak dilwa2ty")
_add("on_my_way", "في الطريق", "On my way", "Fel tareek")
_add("seen", "الكشف تم", "Visit completed", "El kashf tam")
_add("cancelled", "الحجز اتلغى", "Cancelled", "Et2alagha")
_add("didnt_come", "الكشف ما تمش", "Visit did not take place", "El kashf ma tammesh")


def text(key: str, lang: str) -> str:
    return STRINGS[key][lang]


DOCTOR_TEXTS = {
    "clock_format": (
        "{weekday} {day} {month}، {hour}:{minute}",
        "{weekday} {day} {month}, {hour}:{minute}",
    ),
    "login_sub": (
        "عيادة النهارده، إعداداتك، وتقرير الليلة",
        "Tonight's clinic, your settings and evening report",
    ),
    "create_clinic": ("لسه معندكش حساب؟ سجّل عيادتك", "No account yet? Register your clinic"),
    "booked_count": ("محجوز", "Booked"),
    "seen_count": ("اتكشفوا", "Seen"),
    "remaining_count": ("لسه عليهم الدور", "Waiting for their turn"),
    "in_room": ("جوه دلوقتي", "In the room now"),
    "who_next": ("مين يدخل بعده؟", "Who comes in next?"),
    "all_queue": ("كل المرضى بالترتيب", "All patients in queue order"),
    "clinic_link": ("لينك عيادتك", "Your clinic link"),
    "timing_title": ("مواعيد المرضى بتتحسب إزاي", "How patient times are calculated"),
    "brand": ("نوا", "Nowa"),
    "login": ("دخول الدكتور", "Doctor login"),
    "mobile": ("رقم الموبايل", "Mobile number"),
    "password": ("كلمة السر", "Password"),
    "reset": ("نسيت كلمة السر", "Forgot password"),
    "request_code": ("ابعت كود التغيير", "Send reset code"),
    "code": ("الكود (٦ أرقام)", "Code (6 digits)"),
    "new_password": (
        "كلمة السر الجديدة (٨ حروف أو أرقام على الأقل)",
        "New password (at least 8 characters)",
    ),
    "confirm_reset": ("غيّر كلمة السر", "Reset password"),
    "reset_sent": (
        "لو الرقم مسجل، الكود في شات الدكتور على تليجرام. "
        "لو ظهر زر فتح تليجرام، محتاجه أول مرة بس.",
        "If the number is registered, the code is in the doctor’s Telegram chat. "
        "If an Open Telegram button appears, it is only needed the first time.",
    ),
    "on_way_since": ("في الطريق من {time}", "On the way since {time}"),
    "arrived_since": ("وصل {time}", "Arrived {time}"),
    "tonight": ("عيادة النهارده", "Tonight's clinic"),
    "board_title": ("{day} · د. {name}", "{day} · Dr. {name}"),
    "report": ("تقرير العيادة", "Clinic report"),
    "questions": ("أسئلة للدكتور", "Questions for the doctor"),
    "health_answers": ("إجابات صحية", "Health answers"),
    "q_answer": ("✍️ جاوب", "✍️ Answer"),
    "q_save": ("💾 احفظ للكل", "💾 Save for everyone"),
    "q_later": ("⏰ بعدين", "⏰ Later"),
    "q_dismiss": ("❌ تجاهل", "❌ Dismiss"),
    "q_draft_ready": ("راجع الإجابة واحفظها للكل", "Review and save your answer for everyone"),
    "q_no_draft": ("اكتب إجابة الأول", "Write an answer first"),
    "q_stale_save": (
        "الإجابة دي مش متاحة للحفظ. افتح السؤال تاني",
        "This draft is no longer available. Open the question again",
    ),
    "q_already_done": ("السؤال ده اترد عليه أو اتقفل", "This question was answered or closed"),
    "q_text_only": (
        "اكتب إجابة نصية من ١ إلى ١٠٠٠ حرف",
        "Write a text answer of 1 to 1000 characters",
    ),
    "settings": ("إعدادات العيادة", "Clinic settings"),
    "logout": ("خروج", "Log out"),
    "no_evening": ("مفيش عيادة النهارده", "No clinic today"),
    "on_way": ("أنا في الطريق", "I'm on my way"),
    "walk_in": ("من غير حجز", "Without a booking"),
    "undo": ("تراجع عن آخر ضغطة", "Undo last tap"),
    "close": ("خلصت الليلة", "Done for tonight"),
    "cancel": ("إلغاء عيادة الليلة", "Cancel tonight"),
    "close_confirm": ("تأكيد نهاية الليلة؟", "Finish tonight?"),
    "close_untold": (
        ("{count} مرضى لسه ما اتقالهمش ينزلوا. هتوصلهم رسالة إلغاء مع لينك لحجز يوم تاني. تأكيد؟"),
        (
            "{count} patients have not been told to leave yet. They will get a "
            "cancellation message with a rebook link. Confirm?"
        ),
    ),
    "cancel_confirm": (
        "إلغاء الليلة؟ عندك {count} حجوزات نشطة",
        "Cancel tonight? You have {count} active bookings",
    ),
    "area": ("اختار منطقة الانطلاق", "Choose your starting area"),
    "send": ("تأكيد", "Confirm"),
    "save": ("حفظ", "Save"),
    "saved": ("اتحفظ", "Saved"),
    "error": ("الطلب ما تمش. جرّب تاني", "The request failed. Try again"),
    "bookings_outside": (
        "ما ينفعش نحفظ التغيير ده، فيه حجوزات في يوم هيتقفل أو بعد ميعاد النهاية الجديد.",
        (
            "This change cannot be saved. There are bookings on a day you would "
            "close or after the new closing time."
        ),
    ),
    "silent": ("لسه ما أكدش التحرك", "Has not confirmed leaving"),
    "booked": ("محجوز", "Booked"),
    "told_to_leave": (
        "اتقاله ينزل",
        "Told to leave",
    ),
    "on_my_way": ("في الطريق", "On my way"),
    "seen": ("الكشف تم", "Seen"),
    "cancelled": ("اتلغى", "Cancelled"),
    "didnt_come": ("ما جاش", "Did not come"),
    "hours": ("مواعيد العيادة في الأسبوع", "Weekly clinic hours"),
    "weekday": ("اليوم", "Day"),
    "start": ("من", "From"),
    "end": ("لحد", "To"),
    "enabled": ("شغال", "Open"),
    "override": (
        "يوم استثنائي: إجازة أو مواعيد مختلفة",
        "Exception day: a holiday or different hours",
    ),
    "date": ("التاريخ", "Date"),
    "closed": ("مقفول اليوم ده", "Closed on this day"),
    "delete_override": ("امسح", "Remove"),
    "usual_visit_min": ("متوسط مدة الكشف", "Average visit length"),
    "cushion_min": ("المريض يوصل قبل دوره بـ", "Patients arrive before their turn by"),
    "safe_drive_min": ("وقت الطريق لو المنطقة مش معروفة", "Drive time when the area is unknown"),
    "max_per_evening": ("أقصى عدد كشوفات في الليلة", "Maximum visits per evening"),
    "info": ("اللي المريض بيشوفه في الشات", "What patients see in the chat"),
    "price": ("سعر الكشف", "Price"),
    "address": ("العنوان", "Address"),
    "what_to_bring": ("المريض يجيب إيه", "What to bring"),
    "other": ("معلومات تانية", "Other information"),
    "lang": ("لغة الرسايل اللي بتوصلك", "Language of your messages"),
    "secretary_alerts": ("تنبيهات السكرتيرة", "Secretary alerts"),
    "telegram": ("اربط تليجرام", "Link Telegram"),
    "telegram_open": ("افتح تليجرام لتأكيد الربط", "Open Telegram to confirm linking"),
    "telegram_repeated": (
        "اللينك ده اتعمل قبل كده، اضغط تاني لعمل لينك جديد",
        "This link was already created; press again for a new link",
    ),
    "mon": ("الاثنين", "Monday"),
    "tue": ("الثلاثاء", "Tuesday"),
    "wed": ("الأربعاء", "Wednesday"),
    "thu": ("الخميس", "Thursday"),
    "fri": ("الجمعة", "Friday"),
    "sat": ("السبت", "Saturday"),
    "sun": ("الأحد", "Sunday"),
}
DOCTOR_TEXTS.update(
    {
        "override_help": (
            (
                "مسافر، أو عندك إجازة، أو يوم واحد بمواعيد غير المعتاد؟ حدد التاريخ. "
                "نوا مش هيحجز لحد في يوم مقفول."
            ),
            (
                "Travelling, a holiday, or one day with different hours? Pick the date. "
                "Nowa never books anyone on a closed day."
            ),
        ),
        "usual_visit_min_help": (
            (
                "كام دقيقة بياخد الكشف الواحد في المتوسط. نوا بيبدأ بيه وبيتعلم "
                "الرقم الحقيقي من عيادتك."
            ),
            "How long one visit usually takes. Nowa starts from this and learns your real pace.",
        ),
        "cushion_min_help": (
            "هامش أمان عشان الزحمة. كل ما يزيد، المريض بيستنى في العيادة شوية أكتر.",
            (
                "A safety margin for traffic. The larger it is, the longer patients wait at "
                "the clinic."
            ),
        ),
        "safe_drive_min_help": (
            "لو المريض ما قالش منطقته أو المنطقة مش في القايمة، نوا بيستخدم الوقت ده للطريق.",
            "Used when a patient gave no area or the place could not be matched.",
        ),
        "max_per_evening_help": (
            "سيبه فاضي لو مش عايز حد أقصى. اللي بييجي من غير حجز مش بيتحسب.",
            "Leave empty for no limit. Patients without a booking are not counted.",
        ),
        "without_booking_count": ("من غير حجز", "Without a booking"),
        "minutes": ("دقايق", "minutes"),
        "telegram_title": ("تليجرام", "Telegram"),
        "telegram_help": (
            (
                "نوا بيبعتلك على تليجرام كود الدخول، تذكير 'في الطريق' وتقرير "
                "الليلة. افتح الصفحة دي من موبايلك واضغط الزرار، هيفتح تليجرام "
                "على البوت، واضغط Start."
            ),
            (
                "Nowa sends you the login code, the 'on my way' reminder and the "
                "evening report on Telegram. Open this page on your phone and press "
                "the button: Telegram opens on the bot, then press Start."
            ),
        ),
    }
)
for _key, (_ar, _en) in DOCTOR_TEXTS.items():
    STRINGS["doctor." + _key] = {"ar": _ar, "en": _en}
STRINGS["doctor.safe_drive_min_help"]["franco"] = (
    "Law el mareed ma2alsh mante2to aw el makan mesh ma3roof, "
    "Nowa beyestakhdem el wakt da lel taree2."
)


# Approved UI strings.
TELEGRAM_TEXTS = {
    "share_contact": (
        "شارك رقمك عشان نتأكد إنه رقمك",
        "Share your number so we can confirm it is yours",
        "Share your number so we can confirm it is yours",
    ),
    "contact_mismatch": (
        "الرقم اللي في تليجرام مش هو اللي كتبته في الموقع. "
        "اكتب رقم تليجرام في الموقع، أو غيّر رقم تليجرام",
        "Your Telegram number differs from the number you entered on the website. "
        "Enter your Telegram number on the website, or change your Telegram number.",
        "Rakam Telegram mesh howa el rakam elly katabto fel site. "
        "Ekteb rakam Telegram fel site, aw ghayyar rakam Telegram.",
    ),
    "start_first": (
        "ابعت /start من اللينك الأول",
        "Open /start from your link first",
        "Efta7 /start men el link el awel",
    ),
    "code_sent": (
        "الكود هيوصلك هنا على تليجرام",
        "Your code will arrive here on Telegram",
        "El code haywsalak hena 3ala Telegram",
    ),
    "q_answer": ("✍️ جاوب", "✍️ Answer", "✍️ Answer"),
    "q_save": ("💾 احفظ للكل", "💾 Save for everyone", "💾 Save for everyone"),
    "q_later": ("⏰ بعدين", "⏰ Later", "⏰ Later"),
    "q_dismiss": ("❌ تجاهل", "❌ Dismiss", "❌ Dismiss"),
    "q_view": ("اعرض", "View", "View"),
    "q_answer_prompt": (
        "اكتب إجابتك خلال ٣٠ دقيقة",
        "Type your answer within 30 minutes",
        "Type your answer within 30 minutes",
    ),
    "q_already_done": (
        "السؤال ده اتخلص",
        "This question is already done",
        "This question is already done",
    ),
    "q_stale_save": (
        "الإجابة دي مش متاحة للحفظ. افتح السؤال تاني",
        "This draft is no longer available. Open the question again",
        "Open the question again",
    ),
    "q_no_draft": ("اكتب إجابة الأول", "Write an answer first", "Write an answer first"),
    "q_text_only": (
        "اكتب إجابة نصية من ١ إلى ١٠٠٠ حرف",
        "Write a text answer of 1 to 1000 characters",
        "Write a text answer of 1 to 1000 characters",
    ),
    "q_saved": ("اتحفظت الإجابة للكل", "Answer saved for everyone", "Answer saved for everyone"),
    "q_draft_ready": (
        "راجع الإجابة واحفظها للكل",
        "Review and save your answer for everyone",
        "Review and save your answer",
    ),
    "how_to": (
        "افتح لينك تليجرام من رسالة تليجرام أو من لوحة الدكتور",
        "Open the Telegram link from your Telegram message or doctor dashboard",
        "Efta7 link Telegram men Telegram aw lo7et el doctor",
    ),
    "bad_link": (
        "افتح اللينك من رسالة تليجرام تاني",
        "Open the link from your Telegram message again",
        "Efta7 link el Telegram tany",
    ),
    "wrong_kind": (
        "اللينك ده مش للدور المطلوب. افتح اللينك الصحيح تاني",
        "This link is for a different role. Open the correct link again",
        "Efta7 el link el sa7 lel dor el matloob",
    ),
    "already_doctor_chat": (
        "الشات ده مربوط بدكتور بالفعل",
        "This chat is already linked to a doctor",
        "El chat da marboot be doctor already",
    ),
    "linked": ("تمام، تليجرام اتربط", "Telegram linked", "Tamam, Telegram etrabat"),
    "refused": (
        "الطلب ده مش متاح. افتح القائمة تاني",
        "This action is unavailable. Open the menu again",
        "El talab da mesh mota7. Efta7 el menu tany",
    ),
    "menu": ("اختار من القائمة", "Choose from the menu", "Ekhtar men el menu"),
    "bookings": ("حجوزاتي", "My bookings", "7ogozaty"),
    "unlink": ("وقف الرسايل هنا", "Stop messages here", "Wakkaf el rasayel hena"),
    "unlink_confirm": (
        "توقف رسايل كل أرقام الحجز المربوطة بالشات ده؟",
        "Stop messages for every booking phone linked to this chat?",
        "Tewakkaf rasayel kol arkam el 7agz el marboota bel chat da?",
    ),
    "unlinkok": ("أكيد، وقف الرسايل", "Yes, stop messages", "Akeed, wakkaf el rasayel"),
    "unlinked": (
        "تمام، رسايل المرضى هنا اتوقفت",
        "Patient messages here stopped",
        "Tamam, rasayel el marda hena etwakkafet",
    ),
    "no_bookings": (
        "مفيش حجوزات نشطة دلوقتي",
        "No active bookings now",
        "Mafeesh 7ogozat nashta delwa2ty",
    ),
    "booking": (
        "{patient} · د. {doctor}\n{day}، رقم {number}، المعاد المتوقع {time}",
        "{patient} · Dr. {doctor}\n{day}, number {number}, expected time {time}",
        "{patient} · Dr. {doctor}\n{day}, rakm {number}, el ma3ad {time}",
    ),
    "details": ("📄 التفاصيل", "📄 Details", "📄 El tafaseel"),
    "patient_omw": ("🚗 أنا في الطريق", "🚗 I'm on my way", "🚗 Ana fel tareek"),
    "patient_undo": ("↩️ لسه ما اتحركتش", "↩️ I haven't left yet", "↩️ Lessa ma et7arraktesh"),
    "omw": ("🚗 في الطريق", "🚗 On my way", "🚗 Fel tareek"),
    "location": ("ابعت مكانك مرة واحدة", "Share your location once", "Eb3at makanak marra wa7da"),
    "area": ("اختار المنطقة", "Choose the area", "Ekhtar el mantaka"),
    "location_prompt": (
        "ابعت مكانك أو اختار المنطقة",
        "Share your location or choose the area",
        "Eb3at makanak aw ekhtar el mantaka",
    ),
    "location_ignored": (
        "المكان متاح بس قبل ضغطة في الطريق",
        "Location is accepted only before the on-my-way tap",
        "El makan mota7 bas abl daghtet fel tareek",
    ),
    "no_evening": ("مفيش عيادة الليلة", "No evening tonight", "Mafeesh 3eyada el leila"),
    "board": ("عيادة النهارده", "Tonight's clinic", "3eyadet el naharda"),
    "board_row": (
        "{number} {patient}{mark}",
        "{number} {patient}{mark}",
        "{number} {patient}{mark}",
    ),
    "unknown_patient": ("مريض", "Patient", "Mareed"),
    "no_show_mark": (" ⚠️{count}", " ⚠️{count}", " ⚠️{count}"),
    "more": ("المزيد", "More", "El mazeed"),
    "walkin": ("🚶 من غير حجز", "🚶 Without a booking", "🚶 Men gheir 7agz"),
    "undo": ("↩️ تراجع", "↩️ Undo", "↩️ Tarago3"),
    "close": ("✅ خلصت النهارده", "✅ Done for today", "✅ Khelest el naharda"),
    "cancel": ("❌ إلغاء النهارده", "❌ Cancel tonight", "❌ Elgha el naharda"),
    "close_confirm": (
        "تأكيد إنك خلصت النهارده؟",
        "Confirm you're done for today?",
        "Ta2keed ennak khelest el naharda?",
    ),
    "close_untold": (
        "{count} مرضى لسه ما اتنادوش، هيوصلهم رسالة إلغاء بلينك حجز تاني",
        "{count} patients have not been called yet; they will get a cancellation message "
        "with a rebooking link",
        "{count} marda lessa ma etnadoush, hayewsalhom resalet elgha be link 7agz tany",
    ),
    "closeok": ("أكيد، خلصت", "Yes, I'm done", "Akeed, khelest"),
    "cancel_confirm": (
        "تأكيد إلغاء عيادة النهارده؟",
        "Confirm cancelling tonight's clinic?",
        "Ta2keed elgha 3eyadet el naharda?",
    ),
    "cancelok": ("أكيد، إلغاء النهارده", "Yes, cancel tonight", "Akeed, elgha el naharda"),
}
for _key, (_ar, _en, _franco) in TELEGRAM_TEXTS.items():
    STRINGS["tg." + _key] = {"ar": _ar, "en": _en, "franco": _franco}

CHAT_TEXTS = {
    "greeting": (
        "أهلاً، أنا نوا، مساعد عيادة {name}",
        "Hello, I'm Nowa, {name}'s clinic assistant.",
        "Ahlan, ana Nowa, mosa3ed 3eyadet {name}.",
    ),
    "capped": (
        "الشات مش متاح دلوقتي. كلم العيادة {phone}. لو طوارئ اتصل بـ 123.",
        "Chat is unavailable now. Call the clinic on {phone}. In an emergency call 123.",
        "El chat mesh mota7 dlwa2ty. Kallem el 3eyada {phone}. Law tawari2 ettesel be 123.",
    ),
    "clinic_phone": (
        "تليفون العيادة: {phone}",
        "Clinic phone: {phone}",
        "Telephone el 3eyada: {phone}",
    ),
    "name_ask": (
        "اسمك بالكامل؟",
        "Your full name?",
        "Esmak bel kamel?",
    ),
    "phone_ask": (
        "رقم الموبايل اللي هيوصله التأكيد على تليجرام؟",
        "Which mobile number will receive the confirmation on Telegram?",
        "Rakam el mobile elly hayewsalo el ta2keed 3ala Telegram?",
    ),
    "booking_for_ask": (
        "الحجز ليك ولا لحد تاني؟",
        "Is this booking for you or someone else?",
        "El 7agz leek wala le 7ad tany?",
    ),
    "consent": ("عندي إذنه وموافق", "I have permission and agree", "3andy ezno w mwafe2"),
    "consent_done": ("تمام، اختار اليوم.", "Agreed. Choose a day.", "Tamam, ekhtar el yom."),
    "dead_draft": (
        "ابعت اسم المريض ورقم الموبايل تاني عشان نراجع الحجز.",
        "Send the patient's name and mobile again so we can check the booking.",
        "Eb3at esm el mareed w rakam el mobile tany 3ashan nerage3 el 7agz.",
    ),
    "draft_replay_reask": (
        "لإكمال الحجز ابعت الاسم ورقم الموبايل تاني.",
        "To continue booking, send the name and mobile again.",
        "3ashan nekammel el 7agz, eb3at el esm w rakam el mobile tany.",
    ),
    "consent_refused": (
        "وافق على نص الموافقة الحالي الأول، وبعدها اختار اليوم.",
        "Accept the current consent text first, then choose a day.",
        "Wafe2 3ala nass el mowafaka el 7aly el awel, ba3deha ekhtar el yom.",
    ),
    "lookup": (
        "شوف حجزك بالاسم وآخر ٤ أرقام من تليفون الحجز.",
        "Find your booking with the patient name and last 4 phone digits.",
        "Shoof 7agzak bel esm w akher 4 arkam men telephone el 7agz.",
    ),
    "lookup_failed": (
        "ما لقيناش حجز بالبيانات دي. راجع الاسم بالكامل وآخر 4 أرقام وجرب تاني.",
        (
            "No booking matched those details. Check the full name and last 4 phone digits "
            "and try again."
        ),
        "Ma la2enash 7agz. Rage3 el esm bel kamel w akher 4 arkam w garrab tany.",
    ),
    "lookup_locked": (
        "محاولات كتير. جرّب تاني بعد ١٥ دقيقة.",
        "Too many attempts. Try again in 15 minutes.",
        "Mo7awalat keteer. Garrab tany ba3d 15 de2ee2a.",
    ),
    "source_label": (
        "المصدر: {source_title}",
        "Source: {source_title}",
        "El masdar: {source_title}",
    ),
    "area_other": ("مش في القايمة", "Not listed", "Mesh fel kayma"),
    "location": ("📍 موقعي دلوقتي", "📍 My current location", "📍 Mawke3y delwa2ty"),
    "card": (
        "راجع البيانات واختار منطقتك واليوم.",
        "Check the details, choose your area and day.",
        "Rage3 el bayanat w ekhtar mante2tak w el yom.",
    ),
    "no_days": (
        "مفيش أيام متاحة دلوقتي. كلم العيادة.",
        "No days are available now. Call the clinic.",
        "Mafeesh ayam mota7a dlwa2ty. Kallem el 3eyada.",
    ),
    "booked": (
        "حجزك يوم {day}، رقمك {number}، معادك حوالي {time}.",
        "Your booking is {day}, number {number}, around {time}.",
        "7agzak yom {day}, rakamak {number}, 7awaly {time}.",
    ),
    "status": (
        "{day}، رقم {number}، حوالي {time}، {status}",
        "{day}, number {number}, around {time}, {status}",
        "{day}, rakam {number}, 7awaly {time}, {status}",
    ),
    "refused": (
        "ما قدرناش نحجز. راجع بياناتك أو كلم العيادة.",
        "We couldn't book. Check your details or call the clinic.",
        "Ma 2edernash ne7gez. Rage3 bayanatak aw kallem el 3eyada.",
    ),
    "send": ("ابعت", "Send", "Eb3at"),
    "message": ("رسالتك", "Your message", "Resaltak"),
    "name": ("اسم المريض", "Patient name", "Esm el mareed"),
    "last4": ("آخر ٤ أرقام من الموبايل", "Last 4 mobile digits", "Akher 4 arkam men el mobile"),
    "submit_lookup": (
        "شوف حجزك",
        "View your booking",
        "Shoof 7agzak",
    ),
    "error": (
        "حصل خطأ. جرّب تاني.",
        "Something went wrong. Try again.",
        "7asal khata2. Garrab tany.",
    ),
    "draft_retry": (
        "مش فاهم، اختار من الأزرار أو اكتب تاني.",
        "I didn't understand. Choose a button or type again.",
        "Mesh fahem, ekhtar men el azrar aw ekteb tany.",
    ),
    "location_denied": (
        "المتصفح مش سامح بالموقع. اكتب اسم المنطقة.",
        "The browser is not allowing location access. Type the area name.",
        "El browser mesh same7 bel mawke3. Ekteb esm el mante2a.",
    ),
    "location_timeout": (
        "الموقع أخد وقت. اكتب اسم المنطقة.",
        "Getting your location took too long. Type the area name.",
        "El mawke3 akhad wa2t. Ekteb esm el mante2a.",
    ),
    "location_error": (
        "اكتب اسم المنطقة أو المدينة.",
        "Write the area or city.",
        "Ekteb esm el mante2a aw el madina.",
    ),
    "name_invalid": (
        "الاسم حروف بس، من حرفين لستين. اكتب الاسم تاني.",
        "Use letters only, 2 to 60 characters. Please write the name again.",
        "El esm 7oroof bas, men 2 le 60. Ekteb el esm tany.",
    ),
    "phone_invalid": (
        "الرقم لازم يكون ١١ رقم ويبدأ بـ 010 أو 011 أو 012 أو 015، زي "
        "01012345678. اللي كتبته فيه {count} أرقام.",
        "Use 11 digits starting with 010, 011, 012 or 015, like 01012345678. "
        "You entered {count} digits.",
        "El rakam lazm 11 rakam yebda2 be 010 aw 011 aw 012 aw 015, zay "
        "01012345678. Enta katabt {count} arkam.",
    ),
    "for_self": ("ليا", "For me", "Leya"),
    "for_other": ("لحد تاني", "For someone else", "Le 7ad tany"),
    "day_ask": (
        "أقرب مواعيد {doctor}:",
        "{doctor}’s next available days:",
        "A2rab mawa3eed {doctor}:",
    ),
    "day_closed": (
        "{day} العيادة مقفولة. أقرب مواعيد:",
        "The clinic is closed on {day}. Next available days:",
        "El 3eyada ma2foola yom {day}. A2rab mawa3eed:",
    ),
    "day_unavailable": (
        "اليوم ده مش متاح للحجز. أقرب مواعيد:",
        "That day is unavailable for booking. Next available days:",
        "El yom da mesh mota7 lel 7agz. A2rab mawa3eed:",
    ),
    "more_days": ("يوم تاني", "Another day", "Yom tany"),
    "area_ask": (
        "اختار منطقتك",
        "Choose your area",
        "Ekhtar mante2tak",
    ),
    "area_hint": (
        "زي: مدينة نصر، مدينتي، المعادي...",
        "For example: Nasr City, Madinaty, Maadi...",
        "Zay: madinet nasr, madinaty, el ma3adi...",
    ),
    "area_list": (
        "{areas}، واكتب أي منطقة تانية. هتيجي من فين؟",
        "{areas}. You can write any other area. Where will you come from?",
        "{areas}. W ekteb ay mante2a tanya. Hateegy men fein?",
    ),
    "area_outside": (
        "تمام، من {place}. هنحسب وقت الطريق على الطريق ده.",
        "Got it, from {place}. We'll allow time for that trip.",
        "Tamam, men {place}. Hane7seb wakt el taree2 lel meshwar da.",
    ),
    "confirm_summary": (
        "الاسم: {name}\nاليوم: {day}\nجاي من: {area}\nالموبايل: {phone}",
        "Name: {name}\nDay: {day}\nComing from: {area}\nMobile: {phone}",
        "El esm: {name}\nEl yom: {day}\nGay men: {area}\nMobile: {phone}",
    ),
    "confirm": ("تأكيد الحجز", "Confirm booking", "Ta2keed el 7agz"),
    "confirm_other": (
        "تأكيد، وعندي موافقة المريض",
        "Confirm, I have the patient's permission",
        "Ta2keed, w 3andy mowaf2et el mareed",
    ),
    "outside_list": ("برة القايمة", "Outside the list", "Barra el kayma"),
    "draft_expired": (
        "الوقت خلص، نأكد تاني؟",
        "Time ran out, confirm again?",
        "El wakt khelis, ne2akked tany?",
    ),
    "question_noted": (
        "سجلت سؤالك للدكتور.",
        "I noted your question for the doctor.",
        "Sagalt so2alak lel doctor.",
    ),
    "visit_chip": ("احجز كشف", "Book a visit", "E7gez kashf"),
    "booking_chip": ("شوف حجزك", "View your booking", "Shoof 7agzak"),
    "next_booking": (
        "تقدر تشوف حجزك أو تسأل سؤال تاني.",
        "You can view your booking or ask another question.",
        "Te2dar teshoof 7agzak aw tes2al so2al tany.",
    ),
    "next_visit": (
        "تقدر تحجز كشف أو تسأل سؤال تاني.",
        "You can book a visit or ask another question.",
        "Te2dar te7gez kashf aw tes2al so2al tany.",
    ),
    "reply_received": ("الرد وصل.", "Reply received.", "El rad wesel."),
}
CHAT_TEXTS.update(
    {
        "name_other_ask": (
            "اسم المريض بالكامل؟",
            "The patient's full name?",
            "Esm el mareed bel kamel?",
        ),
        "more_days_reply": ("مواعيد تانية:", "More days:", "Mawa3eed tanya:"),
        "outside_summary": (
            "{place} (خارج القايمة)",
            "{place} (not on the list)",
            "{place} (khareg el kayma)",
        ),
        "outside_cairo": ("خارج القايمة", "not on the list", "khareg el kayma"),
        "way_out": (
            "اختار من الأزرار، أو اكتب إلغاء لو مش عايز تكمل الحجز.",
            "Pick one of the buttons, or write cancel to stop this booking.",
            "Ekhtar men el azrar, aw ekteb cancel law mesh 3ayez tekammel.",
        ),
        "booking_stopped": (
            "تمام، وقفت الحجز. لو حبيت تحجز بعدين أنا موجود.",
            "Done, I stopped this booking. I'm here when you want to book.",
            "Tamam, wa2aft el 7agz. Law 7abeet te7gez ba3dein ana mawgood.",
        ),
        "manage_booking": (
            "تقدر تلغي الحجز أو تغير اليوم من لينك الحجز اللي وصلك على تليجرام.",
            "You can cancel or change the day from the booking link sent to you on Telegram.",
            (
                "Te2dar telghi el 7agz aw teghayyar el yom men link el 7agz elly weselak 3ala "
                "Telegram."
            ),
        ),
        "faq_hours": ("مواعيد العيادة", "Clinic hours", "Mawa3eed el 3eyada"),
        "hours_line": (
            "العيادة شغالة {days} من {start} لـ {end}.",
            "The clinic is open {days} from {start} to {end}.",
            "El 3eyada shaghala {days} men {start} le {end}.",
        ),
        "no_hours": (
            "مفيش مواعيد أسبوعية مسجلة. كلم العيادة.",
            "No weekly hours are saved. Call the clinic.",
            "Mafeesh mawa3eed osboo3eya metSaggela. Kallem el 3eyada.",
        ),
        "hours_join": (" و", " and ", " w "),
        "hours_am": ("ص", "AM", "s"),
        "hours_pm": ("م", "PM", "m"),
        "weekday_mon": ("الاثنين", "Monday", "el etnein"),
        "weekday_tue": ("الثلاثاء", "Tuesday", "el talat"),
        "weekday_wed": ("الأربعاء", "Wednesday", "el arba3"),
        "weekday_thu": ("الخميس", "Thursday", "el khamees"),
        "weekday_fri": ("الجمعة", "Friday", "el gom3a"),
        "weekday_sat": ("السبت", "Saturday", "el sabt"),
        "weekday_sun": ("الأحد", "Sunday", "el 7ad"),
    }
)
for _key, (_ar, _en, _franco) in CHAT_TEXTS.items():
    STRINGS["chat." + _key] = {"ar": _ar, "en": _en, "franco": _franco}

# APPROVED under Decisions 048 and 050.
SIGNUP_TEXTS = {
    "patient_door": ("عندي حجز", "I have a booking"),
    "patient_telegram": (
        "افتح لينك حجزك من رسالة تليجرام اللي وصلتك",
        "Open your booking link in the Telegram message you received",
    ),
    "doctor_door": ("أنا دكتور", "I am a doctor"),
    "doctor_start": ("افتح عيادتك على نوا في ٥ دقايق", "Open your clinic on Nowa in 5 minutes"),
    "how": ("إزاي بيشتغل", "How it works"),
    "step1": (
        "المريض بيحجز من لينك العيادة، وبياخد رقم دوره ومعاد تقريبي في رسالة.",
        "The patient books through the clinic link and receives a queue number "
        "and expected time by Telegram.",
    ),
    "step2_before": ("الدكتور بيضغط", "The doctor taps"),
    "on_way": ("أنا في الطريق", "I'm on my way"),
    "step2_after": ("لما يتحرك، وضغطة بعد كل كشف.", "when leaving, then once after each visit."),
    "step3_before": (
        "نوا بيحسب الطابور والطريق، وبيبعت لكل مريض",
        "Nowa calculates the queue and travel, then tells each patient",
    ),
    "leave_now": ("انزل دلوقتي", "Leave now"),
    "step3_after": ("في وقته هو.", "at their own time."),
    "emergency": (
        "نوا مش بديل للطوارئ. لو فيه ألم في الصدر أو إغماء اتصل بـ 123 فورًا.",
        "Nowa does not replace emergency care. For chest pain or fainting, call 123 immediately.",
    ),
    "brand": ("نوا", "Nowa"),
    "headline": ("كل مريض يتحرك من البيت في وقته", "Each patient leaves home at the right time"),
    "intro": (
        "نوا بيبعت لكل مريض رسالة لما ييجي وقت نزوله، على حسب حركة الطابور الحقيقية "
        "في العيادة. مفيش انتظار بالساعات.",
        "Nowa messages each patient on Telegram when it is time to leave, "
        "based on the real clinic queue. "
        "No waiting for hours.",
    ),
    "signup": ("اعمل عيادتك", "Create your clinic"),
    "login": ("دخول الدكتور", "Doctor login"),
    "judge": ("كود لجنة التحكيم", "Judge code"),
    "judge_start": ("ابدأ عيادة تجريبية", "Start a practice clinic"),
    "watch": ("اتفرج على ليلة", "Watch an evening"),
    "mobile": ("موبايل الدكتور", "Doctor mobile"),
    "request_code": ("استلم الكود على تليجرام", "Get the code on Telegram"),
    "code": ("كود التأكيد", "Verification code"),
    "verify": ("أكد الموبايل", "Verify mobile"),
    "name_ar": ("اسم الدكتور بالعربي", "Doctor name in Arabic"),
    "name_en": ("اسم الدكتور بالإنجليزي", "Doctor name in English"),
    "specialty": ("التخصص", "Specialty"),
    "cardiology": ("القلب", "Cardiology"),
    "address": ("عنوان العيادة", "Clinic address"),
    "pin_kind": ("مكان العيادة", "Clinic location"),
    "here": ("أنا في العيادة دلوقتي", "I am at the clinic now"),
    "link": ("لينك خرائط جوجل كامل", "Full Google Maps link"),
    "area": (
        "أقرب منطقة للعيادة (مكان تقريبي)",
        "Nearest area to the clinic (approximate location)",
    ),
    "locate": ("حدد مكان العيادة", "Set the clinic location"),
    "map_link": ("الصق لينك الخريطة", "Paste the map link"),
    "hours": ("مواعيد العيادة في الأسبوع", "Weekly clinic hours"),
    "mon": ("الاثنين", "Monday"),
    "tue": ("الثلاثاء", "Tuesday"),
    "wed": ("الأربعاء", "Wednesday"),
    "thu": ("الخميس", "Thursday"),
    "fri": ("الجمعة", "Friday"),
    "sat": ("السبت", "Saturday"),
    "sun": ("الأحد", "Sunday"),
    "enabled": ("شغال", "Open"),
    "start": ("من", "From"),
    "end": ("لحد", "To"),
    "price": ("سعر الكشف بالجنيه", "Visit price in EGP"),
    "clinic_phone": ("تليفون العيادة (اختياري)", "Clinic phone (optional)"),
    "password": (
        "كلمة السر (٨ حروف أو أرقام على الأقل)",
        "Password (at least 8 characters)",
    ),
    "agreement": ("اتفاق استخدام نوا", "Nowa service agreement"),
    "agreement_version": ("نسخة {version}", "Version {version}"),
    "agree": ("قريت الاتفاق وبوافق عليه", "I have read and accept the agreement"),
    "complete": ("احفظ وافتح العيادة", "Save and open the clinic"),
    "sent": ("الكود اتبعت. اكتبه هنا.", "Code sent. Enter it here."),
    "error": (
        "ما قدرناش نكمل. راجع البيانات وجرب تاني.",
        "Could not complete. Check the details and try again.",
    ),
    "map_error": (
        "حط لينك جوجل مابس كامل، أو اختار أقرب منطقة للعيادة.",
        "Paste the full Google Maps link or choose the nearest area to the clinic.",
    ),
    "not_open": ("التسجيل الحقيقي لسه مش مفتوح.", "Real sign-up is not open yet."),
    "location_error": (
        "ما قدرناش نحدد المكان. اختار أقرب منطقة.",
        "Could not locate you. Choose the nearest area.",
    ),
    "success": ("عيادتك جاهزة", "Your clinic is ready"),
    "chat": ("افتح شات العيادة", "Open clinic chat"),
    "poster": ("اطبع بوستر العيادة", "Print clinic poster"),
    "dashboard": ("افتح لوحة الدكتور", "Open doctor dashboard"),
    "phone": ("رسايل التجربة", "Practice messages"),
    "clock": ("ساعة العيادة التجريبية", "Practice clinic clock"),
    "advance10": ("+١٠ دقايق", "+10 minutes"),
    "advance60": ("+ساعة", "+1 hour"),
    "jump": ("روح لبداية العيادة", "Jump to evening start"),
    "expired": (
        "العيادة التجريبية انتهت. ابدأ واحدة جديدة بكود التحكيم.",
        "This practice clinic has expired. Start a new one with your judge code.",
    ),
    "scan": ("امسح الكود واحجز يومك ورقمك", "Scan to book your day and queue number"),
    "print": ("اطبع", "Print"),
}
for _key, (_ar, _en) in SIGNUP_TEXTS.items():
    STRINGS["signup." + _key] = {"ar": _ar, "en": _en}

DEMO_TEXTS = {
    "title": ("شاهد ليلة كاملة", "Watch a full evening"),
    "intro": (
        (
            "عيادة ومرضى خياليين. نفس محرك الطابور والرسايل، من غير ذكاء "
            "اصطناعي. وقت الطريق ثابت حسب المنطقة. الأوقات والنتائج هنا محاكاة."
        ),
        (
            "Fictional clinic and patients. The real queue and message engine, "
            "with no AI. Travel time is fixed by area. Times and results are "
            "simulated."
        ),
    ),
    "play": ("تشغيل", "Play"),
    "pause": ("إيقاف مؤقت", "Pause"),
    "restart": ("ليلة جديدة", "New evening"),
    "speed": ("السرعة", "Speed"),
    "dashboard": ("لوحة الدكتور", "Doctor dashboard"),
    "report": ("تقرير الليلة", "Evening report"),
    "queue": ("الطابور", "Queue"),
    "phones": (
        "رسايل المرضى على الشاشة (كريم أول واحد)",
        "Patient messages on screen (Karim first)",
    ),
    "timeline": ("اللي حصل الليلة", "Tonight so far"),
    "travel": ("وقت طريق الدكتور", "Doctor's travel time"),
    "minutes": ("دقيقة", "minutes"),
    "closed": ("الليلة خلصت", "Evening closed"),
    "walkin": ("من غير حجز", "Without a booking"),
    "doctor": ("تليجرام الدكتور", "Doctor Telegram"),
    "watch_error": (
        "ما قدرناش نكمل العرض. جرّب ليلة جديدة.",
        "Could not continue. Start a new evening.",
    ),
    "public_book": ("جرّب الحجز من غير ذكاء اصطناعي", "Book without AI"),
    "start_booking": ("ابدأ حجز خيالي", "Start a fictional booking"),
    "banner": ("لو حالة طارئة اتصل بـ 123", "For an emergency call 123"),
    "patient_phone": ("تليجرام المريض (تجربة)", "Patient Telegram (demo)"),
    "book_as": ("احجز باسم {name} (خيالي)", "Book as {name} (fictional)"),
    "area": ("اختار المنطقة", "Choose an area"),
    "area_other": ("مش في القايمة", "Not listed"),
    "confirm_intro": (
        "تأكيد الحجز والموافقة على النص الموضح فوق",
        "Confirm booking and agree to the consent above",
    ),
    "confirm": ("موافق، أكد الحجز", "I agree, confirm booking"),
    "change_day": ("اختار يوم تاني", "Choose another day"),
    "error": ("الطلب ما تمش. جرّب تاني.", "Could not complete. Try again."),
    "phone_error": (
        "ما قدرناش نحمّل رسايل التجربة. جرّب تاني.",
        "Could not load the demo messages. Try again.",
    ),
    "start_error": (
        "ما قدرناش نبدأ الحجز. حدّث الصفحة وجرّب تاني.",
        "Could not start booking. Refresh the page and try again.",
    ),
}
for _key, (_ar, _en) in DEMO_TEXTS.items():
    STRINGS["demo." + _key] = {"ar": _ar, "en": _en}
STRINGS["signup.public_book"] = STRINGS["demo.public_book"]

# Presentation strings; no message-template or engine changes.
_add("your_turn", "أهلاً {name}، دورك", "Hello {name}, your number", "Ahlan {name}, dorak")
_add("leave_now", "انزل دلوقتي", "Leave now", "Enzel delwa2ty")
_add("leave_number", "{name}، دورك رقم", "{name}, your number", "{name}, dorak rakm")
_add(
    "travel",
    "الطريق حوالي {minutes} دقيقة. هتوصل قبل دورك بشوية.",
    "Travel is about {minutes} minutes. You will arrive shortly before your turn.",
    "El tareek 7awaly {minutes} de2ee2a. Hatewsal abl dorak beshowaya.",
)
_add(
    "tap_help",
    "الضغطة دي بتقول للدكتور إنك اتحركت. لو اتأخرت، اضغط لسه ما اتحركتش.",
    "This tap tells the doctor you have left. If delayed, tap I haven't left yet.",
    "El daghta de bet2ool lel doctor ennak et7arrakt. Law et2akhart, edghat lessa ma et7arraktesh.",
)
_add(
    "emergency",
    "لو حسيت بألم في الصدر أو إغماء، متستناش دورك. اتصل بـ 123 فورًا.",
    "For chest pain or fainting, do not wait for your turn. Call 123 immediately.",
    "Law 7asseet be alam fel sadr aw eghma2, matestannash dorak. Ettesel be 123 fawran.",
)
_add("in_room", "جوه دلوقتي", "In the room now", "Gowa delwa2ty")
for _key, _values in {
    "emergency": (
        "لو طوارئ، اتصل بـ 123. نوا مش بديل للطوارئ.",
        "In an emergency, call 123. Nowa does not replace emergency care.",
        "Law tawari2, ettesel be 123. Nowa mesh badeel lel tawari2.",
    ),
    "clinic_title": ("عيادة {name}", "{name}'s clinic", "3eyadet {name}"),
    "faq_price": ("سعر الكشف", "Price", "Se3r el kashf"),
    "faq_address": ("العنوان", "Address", "El 3enwan"),
    "faq_what_to_bring": ("أجيب معايا إيه؟", "What to bring?", "Ageeb ma3aya eh?"),
    "faq_other": ("معلومات تانية", "Other info", "Ma3lomat tanya"),
    "book_chip": ("احجز", "Book", "E7gez"),
    "book_text": ("عايز أحجز", "I want to book", "3ayez a7gez"),
}.items():
    STRINGS["chat." + _key] = dict(zip(("ar", "en", "franco"), _values, strict=True))

# Story page copy; the inline number spans are intentional.
UI_TEXTS = {
    "front_nowa_waiting_room_agent": ("نوا · مساعد الانتظار", "Nowa · waiting-room agent"),
    "front_patients_wait_at_home_not_in_the": (
        "المريض يستنى دوره في بيته، مش في العيادة.",
        "Patients wait at home, not in the waiting room.",
    ),
    "front_nowa_tells_each_patient_on_telegram_when": (
        "نوا بيقول لكل مريض على تليجرام امتى ينزل من البيت، على حسب "
        "الدكتور فين والطابور ماشي بأي سرعة. يوصل قبل دوره بشوية، مش "
        "قبله بساعتين.",
        "Nowa tells each patient on Telegram when to leave home, based "
        "on where the doctor is and how fast the queue moves. They "
        "arrive just before their turn, not two hours early.",
    ),
    "front_see_nowa_working": ("شوف نوا شغالة", "See Nowa working"),
    "front_i_m_a_doctor": ("أنا دكتور", "I'm a doctor"),
    "front_mahmoud_number": ("· محمود، رقم", "· Mahmoud, number"),
    "front_got_leave_now": ('، وصلته "انزل دلوقتي"', ', got "leave now"'),
    "front_how_it_works": ("نوا بيشتغل إزاي", "How it works"),
    "front_one_evening_three_moments": ("ليلة واحدة، تلات لحظات", "One evening, three moments"),
    "front_the_doctor_taps_twice_nowa_does_the": (
        "ضغطة لما الدكتور يتحرك، وضغطة بعد كل كشف. نوا بيحسب المواعيد وبيبعت الرسايل.",
        (
            "One tap when the doctor leaves, then one after each visit. Nowa "
            "calculates the times and sends the messages."
        ),
    ),
    "front_sunday": ("الأحد ·", "Sunday ·"),
    "front_nowa_dr_hesham_s_clinic": ("نوا · عيادة د. هشام", "Nowa · Dr. Hesham's clinic"),
    "front_bot": ("بوت", "Bot"),
    "front_sun_4_oct": ("الأحد، 4 أكتوبر", "Sun, 4 Oct"),
    "front_mahmoud_your_booking_with_dr_hesham_mostafa": (
        "محمود: حجزك مع د. هشام مصطفى يوم الثلاثاء، رقمك",
        "Mahmoud: your booking with Dr. Hesham Mostafa is on Tuesday, number",
    ),
    "front_around": ("، معادك حوالي", ", around"),
    "front_and_it_may_move_later_we_ll": (
        "وممكن يتأخر. هنقولك على تليجرام امتى تتحرك.",
        "and it may move later. We'll tell you on Telegram when to leave.",
    ),
    "front_open_booking_link": ("افتح لينك الحجز", "Open booking link"),
    "front_karim_books_his_father_and_gets_number": (
        "كريم بيحجز لأبوه، وياخد رقم 7",
        "Karim books for his father and gets number 7",
    ),
    "front_from_the_clinic_link_the_number_and": (
        "من لينك العيادة. الرقم والمعاد التقريبي يوصلوا على تليجرام في ثانية.",
        "From the clinic link. The number and rough time arrive on Telegram in a second.",
    ),
    "front_tuesday": ("الثلاثاء ·", "Tuesday ·"),
    "front_nowa": ("نوا", "Nowa"),
    "front_tonight_s_clinic": ("عيادة النهارده", "Tonight's clinic"),
    "front_dr_hesham_the_clinic_should_start_at": (
        "د. هشام، العيادة المفروض تبدأ",
        "Dr. Hesham, the clinic should start at",
    ),
    "front_and_you_haven_t_tapped_on_my": (
        'ولسه ما دوستش "في الطريق". عندك',
        'and you haven\'t tapped "on my way". You have',
    ),
    "front_bookings_today_are_you_on_your_way": (
        "حجز النهارده. إنت في الطريق؟",
        "bookings today. Are you on your way?",
    ),
    "front_on_my_way": ("🚗 في الطريق", "🚗 On my way"),
    "front_drive_about": ("الطريق حوالي", "Drive about"),
    "front_min_queue_calculated": ("دقيقة · الطابور اتحسب", "min · queue calculated"),
    "front_the_doctor_taps_on_my_way": ('الدكتور بيضغط "في الطريق"', 'The doctor taps "on my way"'),
    "front_one_tap_leaving_the_hospital_nowa_times": (
        "ضغطة واحدة وهو خارج من المستشفى. نوا بيحسب الطريق والطابور كله من اللحظة دي.",
        "One tap leaving the hospital. Nowa times the drive and the whole queue from that moment.",
    ),
    "front_tuesday_32": ("الثلاثاء ·", "Tuesday ·"),
    "front_nowa_dr_hesham_s_clinic_33": ("نوا · عيادة د. هشام", "Nowa · Dr. Hesham's clinic"),
    "front_bot_34": ("بوت", "Bot"),
    "front_mahmoud_leave_now_for_dr_hesham_mostafa": (
        "محمود: اتحرك دلوقتي لعيادة د. هشام مصطفى، دورك قرب (رقم",
        "Mahmoud: leave now for Dr. Hesham Mostafa's clinic, your turn is close (number",
    ),
    "front_when_you_leave_tap_here": ("). لما تتحرك اضغط هنا:", "). When you leave, tap here:"),
    "front_i_m_on_my_way": ("أنا في الطريق", "I'm on my way"),
    "front_i_m_on_my_way_38": ("🚗 أنا في الطريق", "🚗 I'm on my way"),
    "front_details": ("📄 التفاصيل", "📄 Details"),
    "front_leave_now_at_the_right_minute": (
        '"انزل دلوقتي" في الدقيقة الصح',
        '"Leave now" at the right minute',
    ),
    "front_each_patient_at_their_own_time_by": (
        "لكل مريض في وقته هو، على حسب طريقه. يوصل قبل دوره بشوية.",
        "Each patient at their own time, by their own drive. They arrive just before their turn.",
    ),
    "front_for_the_doctor": ("للدكتور", "For the doctor"),
    "front_two_taps_all_evening": ("في الطريق، وبعد كل كشف", "On my way, then after each visit"),
    "front_on_my_way_when_you_leave_who": (
        '"في الطريق" لما تتحرك، و"مين يدخل" بعد كل كشف. مفيش صالة زحمة ولا تليفونات للسكرتيرة.',
        '"On my way" when you leave, "who comes in" after each visit. '
        "No packed waiting room, no calls to the secretary.",
    ),
    "front_min": ("د", "min"),
    "front_for_the_patient": ("للمريض", "For the patient"),
    "front_wait_at_home_not_in_the_hall": (
        "تستنى في بيتك، مش في الصالة",
        "Wait at home, not in the hall",
    ),
    "front_one_telegram_message_tells_you_when_to": (
        "رسالة واحدة على تليجرام تقولك انزل امتى. متوسط الانتظار في العيادة حوالي",
        "One Telegram message tells you when to leave. Average clinic wait about",
    ),
    "front_minutes_instead_of_hours_simulated": (
        "دقيقة بدل ساعات (محاكاة).",
        "minutes instead of hours (simulated).",
    ),
    "front_nowa_does_not_replace_emergency_care_for": (
        "نوا مش بديل للطوارئ. لو فيه ألم في الصدر أو إغماء اتصل بـ",
        "Nowa does not replace emergency care. For chest pain or fainting, call",
    ),
    "front_immediately": ("فورًا.", "immediately."),
    "front_karim_s_telegram": ("تليجرام كريم", "Karim's Telegram"),
    "front_doctor_s_telegram": ("تليجرام الدكتور", "Doctor's Telegram"),
    "front_karim_s_telegram_54": ("تليجرام كريم", "Karim's Telegram"),
}

UI_TEXTS.update(
    {
        "switch_language": ("English", "العربية"),
        "eyebrow": ("نوا · مساعد الانتظار", "Nowa · waiting-room agent"),
        "demo_eyebrow": ("تجربة", "Demo"),
        "demo_title": ("جرّب نوا بنفسك", "Try Nowa yourself"),
        "demo_intro": (
            "عيادة د. هشام مصطفى، ليلة الثلاثاء، 18 حجز. اختار من فين تبدأ.",
            "Dr. Hesham Mostafa's clinic, Tuesday evening, 18 bookings. Pick where to start.",
        ),
        "door_live": ("شاهد ليلة كاملة", "Watch a full evening"),
        "door_live_sub": (
            "الليلة كلها في حوالي 4 دقايق: الدكتور، الطابور، وكل رسالة وهي بتوصل.",
            "The whole evening in about 4 minutes: the doctor, the "
            "queue, every message as it lands.",
        ),
        "door_booking": ("جرّب الحجز كمريض", "Book as a patient"),
        "door_booking_sub": (
            "احجز دور خيالي في شات العيادة، وشوف رسالة الحجز توصل على تليجرام.",
            "Book a fictional turn in the clinic chat and watch the message reach Telegram.",
        ),
        "door_board": ("لوحة الدكتور", "Doctor's board"),
        "door_board_sub": (
            "اللي الدكتور بيشوفه ويضغطه الليلة.",
            "What the doctor sees and taps tonight.",
        ),
        "credentials": (
            "الدخول: {mobile} · كلمة السر: {password}",
            "Login: {mobile} · password: {password}",
        ),
        "door_report": ("تقرير الليلة", "Evening report"),
        "door_report_sub": (
            "مين جه، مين ما جاش، والمريض استنى قد إيه فعلًا. التقرير يظهر لما الليلة تخلص.",
            "Who came, who didn't, and how long patients waited. The "
            "report appears when the evening closes.",
        ),
        "live": ("مباشر", "Live"),
        "ready": ("جاهز", "Ready"),
        "after_close": ("بعد ما الليلة تخلص", "After the evening ends"),
        "demo_note": (
            "كل حاجة هنا شغالة على محرك نوا الحقيقي، والعيادة والمرضى خياليين.",
            "Everything here runs on the real Nowa engine; the clinic and patients are fictional.",
        ),
        "idle_title": ("ابدأ ليلة الثلاثاء", "Start Tuesday evening"),
        "idle_sub": (
            "18 حجز عند د. هشام. الليلة كلها في حوالي 4 دقايق.",
            "18 bookings with Dr. Hesham. The whole evening in about 4 minutes.",
        ),
        "clinic_name": ("عيادة د. هشام مصطفى", "Dr. Hesham Mostafa's clinic"),
        "clinic_line": (
            "القلب · مصر الجديدة · عيادة خيالية",
            "Cardiology · Heliopolis · fictional clinic",
        ),
        "clinic_clock": ("ساعة العيادة", "Clinic clock"),
        "doctor_waiting": ("الدكتور لسه في المستشفى", "Doctor still at the hospital"),
        "doctor_on_way": ("الدكتور في الطريق · حوالي {m} د", "Doctor on the way · about {m} min"),
        "doctor_arrived": ("الدكتور وصل · {time}", "Doctor arrived · {time}"),
        "doctor_closed": ("خلصت الليلة", "Evening done"),
        "play": ("تشغيل", "Play"),
        "pause": ("إيقاف مؤقت", "Pause"),
        "restart": ("ليلة جديدة", "New evening"),
        "speed": ("السرعة", "Speed"),
        "dashboard": ("افتح لوحة الدكتور", "Open the doctor's board"),
        "report_link": ("التقرير الكامل", "Full report"),
        "queue": ("الطابور", "Queue"),
        "final_queue": ("الطابور في الآخر", "Final queue"),
        "legend_waiting": ("مستني", "Waiting"),
        "legend_moving": ("متحرك", "Moving"),
        "legend_finished": ("خلص", "Finished"),
        "legend_number": ("1", "1"),
        "legend_walkin_marker": ("+", "+"),
        "feed": ("الرسائل", "Messages"),
        "feed_sub": ("على تليجرام · الأحدث فوق", "on Telegram · newest first"),
        "timeline": ("اللي حصل الليلة", "Tonight so far"),
        "now": ("دلوقتي", "Now"),
        "room": ("جوه دلوقتي", "In the room"),
        "empty_room": ("لسه مفيش حد جوه", "No one in the room yet"),
        "next": ("اللي عليه الدور", "Next up"),
        "no_next": ("مفيش حد مستني", "No one waiting"),
        "room_minutes": ("بقاله {m} د", "for {m} min"),
        "pace": ("الكشف بياخد حوالي", "A visit takes about"),
        "learned": ("اتعلم من الليلة دي", "learned tonight"),
        "minutes": ("د", "min"),
        "booked": ("محجوز", "Booked"),
        "told_to_leave": (
            "اتقاله ينزل",
            "Told to leave",
        ),
        "on_my_way": ("في الطريق", "On the way"),
        "in_room": (
            "في الكشف",
            "In the visit",
        ),
        "seen": ("اتكشف", "Seen"),
        "cancelled": ("اتلغى", "Cancelled"),
        "didnt_come": ("ما جاش", "Didn't come"),
        "walkin": ("من غير حجز", "Without a booking"),
        "doctor": ("الدكتور", "Doctor"),
        "number": ("رقم {n}", "number {n}"),
        "link_booking": ("افتح لينك الحجز", "Open booking link"),
        "link_way": ("أنا في الطريق", "I'm on my way"),
        "link_rebook": ("احجز يوم تاني", "Book another day"),
        "failed": ("ما وصلتش · الدكتور اتبلّغ", "Not delivered · doctor alerted"),
        "report_title": ("ليلة الثلاثاء في أرقام", "Tuesday evening in numbers"),
        "report_booked": (
            "محجوزين (غير {cancelled} اتلغى)",
            "Booked ({cancelled} cancelled)",
        ),
        "report_came": (
            "اتكشفوا، بما فيهم اللي من غير حجز",
            "Seen, including patients without a booking",
        ),
        "report_no_show_count": (
            "ما جوش",
            "Did not come",
        ),
        "report_walk_ins": ("جم من غير حجز واتكشفوا", "Came without a booking, seen"),
        "report_avg_wait": ("متوسط الانتظار في العيادة (تقريبًا)", "Avg clinic wait (approx.)"),
        "with_nowa": ("مع نوا", "With Nowa"),
        "without_nowa": ("من غير نوا", "Without Nowa"),
        "baseline": ("229 د (محاكاة)", "229 min (simulated)"),
        "report_sub": (
            "الأرقام دي محاكاة على عيادة خيالية.",
            "Simulated numbers on a fictional clinic.",
        ),
        "watch_error": (
            "ما قدرناش نكمل العرض. جرّب ليلة جديدة.",
            "Could not continue. Start a new evening.",
        ),
        "practice_tools": ("أدوات التجربة", "Practice tools"),
        "practice_tools_sub": (
            "ساعة العيادة التجريبية ورسايل التجربة",
            "Practice clock and practice messages",
        ),
        "empty": ("مفيش", "None"),
        "other_patient": ("أو حد تاني", "Or someone else"),
        "call_in": ("دخّل {name}", "Call in {name}"),
        "patient_note": (
            'الرسالة هتوصلك على تليجرام. خليك في البيت، وأول ما ييجي وقتك هنبعتلك "انزل دلوقتي".',
            "The message will reach you on Telegram. Stay home; when it"
            ' is time we will send "leave now".',
        ),
        "action_booking_created": (
            "اتسجل حجز {name} (رقم {n})",
            "Booking recorded for {name} (number {n})",
        ),
        "action_message_enqueue": ("نوا جهّز رسالة على تليجرام", "Nowa prepared a Telegram message"),
        "action_leave_now": (
            'رسالة "انزل دلوقتي" لـ{name} (رقم {n})',
            '"Leave now" sent to {name} (number {n})',
        ),
        "action_reminder": (
            'نوا فكّر الدكتور: العيادة بدأت ولسه ما ضغطش "في الطريق"',
            'Nowa reminded the doctor: the clinic started and he has not tapped "on my way"',
        ),
        "action_doctor_on_my_way": ('الدكتور ضغط "في الطريق"', 'The doctor tapped "on my way"'),
        "action_who_comes_in": (
            "الدكتور دخّل المريض اللي عليه الدور",
            "The doctor called in the next patient",
        ),
        "action_patient_on_my_way": (
            'المريض ضغط "أنا في الطريق"',
            'A patient tapped "I am on my way"',
        ),
        "action_patient_undo_on_my_way": ("المريض قال لسه ما اتحركش", "A patient has not left yet"),
        "action_booking_cancelled": ("{name} (رقم {n}) لغى حجزه", "{name} (number {n}) cancelled"),
        "action_message_failure": (
            "الرسالة ما وصلتش لـ{name} (رقم {n})، الدكتور اتبلّغ",
            "Message to {name} (number {n}) failed; doctor alerted",
        ),
        "action_close_evening": ("الدكتور قفل الليلة", "The doctor closed the evening"),
        "action_chat_in": ("المريض سأل سؤال صحي", "A patient asked a health question"),
        "action_chat_out": ("نوا جاوب من مكتبة الصحة", "Nowa answered from the health library"),
        "action_message_result": ("اتحدّثت حالة الرسالة", "Message status updated"),
        "action_question_logged": ("اتسجل سؤال للدكتور", "A question was recorded for the doctor"),
        "action_patient_named_way": (
            '{name} (رقم {n}) ضغط "أنا في الطريق"',
            '{name} (number {n}) tapped "I am on my way"',
        ),
        "action_patient_named_undo": (
            "{name} (رقم {n}) قال لسه ما اتحركش",
            "{name} (number {n}) has not left yet",
        ),
        "action_named_who": (
            "الدكتور دخّل {name} (رقم {n})",
            "The doctor called in {name} (number {n})",
        ),
    }
)

UI_TEXTS.update(
    {
        "action_demo_copy_created": (
            "اتجهزت العيادة الخيالية",
            "The fictional clinic was prepared",
        ),
        "action_doctor_login": ("لوحة الدكتور جاهزة", "The doctor's board is ready"),
        "action_message_delivery": ("الرسالة وصلت", "The message was delivered"),
        "action_send_attempt": ("نوا حاول يبعت الرسالة", "Nowa attempted to send the message"),
    }
)

# Presentation labels only: template bodies and outbox delivery stay unchanged.
MESSAGE_LABELS = {
    "1": "message_booking",
    "2": "message_leave",
    "3": "message_cancelled",
    "4": "message_clinic_cancelled",
    "5": "message_doctor_reminder",
    "6": "message_report",
    "op:question_card": "message_question",
    "op:question_card_count": "message_question",
    "op:doctor_alert_unreachable": "message_delivery_alert",
    "op:doctor_alert_brake": "message_delivery_alert",
    "op:reset_code": "message_code",
    "op:signup_code": "message_code",
    "op:secretary_link": "message_link",
    "op:secretary_linked": "message_linked",
    "op:secretary_unlinked": "message_unlinked",
    "op:doctor_linked": "message_linked",
    "op:patient_linked": "message_linked",
    "op:patient_unlinked": "message_unlinked",
    "op:bookings_header": "message_bookings",
    "op:bookings_line": "message_bookings",
    "op:bookings_empty": "message_bookings",
    "op:just_filled": "message_capacity",
    "op:triage_urgent": "message_triage",
    "op:triage_unclear": "message_triage",
    "op:chain_fallback": "message_triage",
    "op:health_no_answer": "message_question",
    "op:out_of_specialty": "message_specialty",
    "op:phone_cap": "message_capacity",
}
UI_TEXTS.update(
    {
        "message_booking": ("تأكيد الحجز", "Booking confirmed"),
        "message_leave": ("انزل دلوقتي", "Leave now"),
        "message_cancelled": ("الحجز اتلغى", "Booking cancelled"),
        "message_clinic_cancelled": ("العيادة اتلغت", "Clinic cancelled"),
        "message_doctor_reminder": ("تذكير للدكتور", "Doctor reminder"),
        "message_report": ("تقرير الليلة", "Evening report"),
        "message_question": ("سؤال للدكتور", "Question for the doctor"),
        "message_delivery_alert": ("تنبيه إرسال", "Delivery alert"),
        "message_code": ("كود", "Code"),
        "message_link": ("لينك تليجرام", "Telegram link"),
        "message_linked": ("تليجرام اتفعل", "Telegram linked"),
        "message_unlinked": ("تليجرام اتوقف", "Telegram unlinked"),
        "message_bookings": ("قائمة الحجوزات", "Bookings list"),
        "message_capacity": ("حد الحجوزات", "Booking limit"),
        "message_triage": ("توجيه صحي", "Health guidance"),
        "message_specialty": ("خارج التخصص", "Outside specialty"),
        "action_walk_in": (
            "{name} (رقم {n}) دخل للكشف من غير حجز",
            "{name} (number {n}) entered for a visit without a booking",
        ),
    }
)

# All observed replay kinds have bilingual sentences. Noise is deliberately hidden
# on the stage, but mapped so a new replay kind cannot silently enter the UI.
ACTION_SENTENCES = {
    "demo_copy_created": "action_demo_copy_created",
    "doctor_login": "action_doctor_login",
    "message_delivery": "action_message_delivery",
    "send_attempt": "action_send_attempt",
    "booking_created": "action_booking_created",
    "message_enqueue": "action_message_enqueue",
    "message_result": "action_message_result",
    "doctor_on_my_way": "action_doctor_on_my_way",
    "who_comes_in": "action_who_comes_in",
    "patient_on_my_way": "action_patient_on_my_way",
    "patient_undo_on_my_way": "action_patient_undo_on_my_way",
    "booking_cancelled": "action_booking_cancelled",
    "message_failure": "action_message_failure",
    "close_evening": "action_close_evening",
    "chat_in": "action_chat_in",
    "chat_out:normal": "action_chat_out",
    "question_logged": "action_question_logged",
}
UI_TEXTS.update(
    {
        "report_seen_booked": ("اتكشفوا من المحجوزين", "Seen, of the booked"),
        "report_total_seen": ("إجمالي الكشوفات", "Total seen"),
        "privacy": ("سياسة الخصوصية", "Privacy policy"),
        "door_chat": ("جرّب الشات", "Try the chat"),
        "door_chat_sub": (
            "اسأل، احجز، جرّب «ألم شديد في صدري وعرقان»",
            "Ask, book, try 'severe chest pain and sweating'",
        ),
        "story_title": ("كل اللي نوا بيعمله", "Everything Nowa does"),
        "story_booking_title": ("الحجز من الشات", "Booking by chat"),
        "story_booking_text": (
            "المريض بيكتب زي ما بيكلم السكرتيرة، ونوا بيحجزله يوم ورقم وميعاد متوقع",
            (
                "Patients write as if talking to the secretary. Nowa books a "
                "day, queue number and expected time."
            ),
        ),
        "story_travel_title": ("بيحسب الطريق", "Travel time"),
        "story_travel_text": (
            "بيحسب الطريق للدكتور ولكل مريض من منطقته",
            "Travel time for the doctor and for every patient from their own area",
        ),
        "story_message_title": ("رسالة واحدة في الدقيقة الصح", "One message at the right minute"),
        "story_message_text": (
            "كل مريض بتوصله رسالة «انزل دلوقتي» في الدقيقة اللي تناسب دوره وطريقه.",
            (
                'Each patient gets one "leave now" message at the minute that fits their turn '
                "and their road."
            ),
        ),
        "story_emergency_title": ("الطوارئ الأول", "Emergencies first"),
        "story_emergency_text": (
            "لو المريض وصف عرض خطر، نوا بيقوله يتصل بـ 123 فورًا ومش بيحجزله.",
            (
                "If a patient describes a dangerous symptom, Nowa tells them to call 123 now "
                "and does not book."
            ),
        ),
        "story_health_title": ("إجابات صحية بالمصدر", "Health answers with the source"),
        "story_health_text": (
            "أسئلة المرضى الصحية بيجاوبها من مصادر طبية معتمدة، بالمصدر",
            "Health questions answered from approved medical sources, with the source",
        ),
        "story_doctor_title": (
            "السؤال للدكتور، والتقرير آخر الليلة",
            "Doctor questions and the evening report",
        ),
        "story_doctor_text": (
            "اللي محتاج الدكتور بيوصل للدكتور، وآخر الليلة تقرير بالأرقام",
            "What needs the doctor reaches the doctor, and the evening ends with a report",
        ),
    }
)
UI_TEXTS.update({"kind_" + kind: UI_TEXTS[key] for kind, key in ACTION_SENTENCES.items()})
for _key, (_ar, _en) in UI_TEXTS.items():
    STRINGS["ui." + _key] = {"ar": _ar, "en": _en}
# Existing drawn phone titles, now the same Telegram component on every surface.
for _namespace, _key in (("signup", "phone"), ("demo", "patient_phone")):
    (SIGNUP_TEXTS if _namespace == "signup" else DEMO_TEXTS)[_key] = (
        "تليجرام (تجربة)",
        "Telegram (demo)",
    )
    STRINGS[_namespace + "." + _key] = {"ar": "تليجرام (تجربة)", "en": "Telegram (demo)"}

for _key in ("empty", "call_in"):
    DOCTOR_TEXTS[_key] = UI_TEXTS[_key]
    STRINGS["doctor." + _key] = STRINGS["ui." + _key]

STRINGS["patient.v2_note"] = {
    "ar": UI_TEXTS["patient_note"][0],
    "en": UI_TEXTS["patient_note"][1],
    "franco": "El resala hatewsalak 3ala Telegram. Khalik fel beit; "
    "lama yeegy waktak haneb3atlak enzel delwa2ty.",
}

STRINGS["chat.telegram_note"] = {
    "ar": 'هتوصلك هناك رسالة الحجز، و"انزل دلوقتي" لما ييجي وقتك، ولينك فيه دورك.',
    "en": 'You\'ll get the booking message there, "leave now" when it is time, '
    "and a link with your turn.",
    "franco": "Hayewsalak henak resalet el 7agz, w enzel delwa2ty lama yeegy waktak, "
    "w link feeh dorak.",
}

# doctor-only asker identities; never used in Telegram cards.
DOCTOR_TEXTS["question_asker"] = (
    "{name} · رقم {number} · {day}",
    "{name} · number {number} · {day}",
)
STRINGS["doctor.question_asker"] = {
    "ar": DOCTOR_TEXTS["question_asker"][0],
    "en": DOCTOR_TEXTS["question_asker"][1],
    "franco": "{name} · rakam {number} · {day}",
}
DOCTOR_TEXTS["question_anonymous"] = (
    "مريض من الشات، لسه ما حجزش",
    "Patient from chat, not booked yet",
)
STRINGS["doctor.question_anonymous"] = {
    "ar": DOCTOR_TEXTS["question_anonymous"][0],
    "en": DOCTOR_TEXTS["question_anonymous"][1],
    "franco": "Mareed men el chat, lessa ma 7agazsh",
}

# Known command refusals keep their existing generic request-error wording.
# Register them explicitly so presentation lookups never need an error fallback.
for _key in (
    "invalid_state",
    "already_seen",
    "invalid_booking",
    "evening_closed",
    "nothing_to_undo",
    "changed_since",
    "invalid_token",
    "evening_running",
    "q_refused",
):
    DOCTOR_TEXTS[_key] = DOCTOR_TEXTS["error"]
    STRINGS["doctor." + _key] = STRINGS["doctor.error"]
DOCTOR_TEXTS["q_answer_prompt"] = DOCTOR_TEXTS["q_answer"]
STRINGS["doctor.q_answer_prompt"] = STRINGS["doctor.q_answer"]

# Behaviour copy. Existing unrelated labels remain unchanged.
DOCTOR_TEXTS["login_refused"] = (
    "رقم الموبايل أو كلمة السر غلط",
    "Wrong mobile number or password",
)
STRINGS["doctor.login_refused"] = {
    "ar": DOCTOR_TEXTS["login_refused"][0],
    "en": DOCTOR_TEXTS["login_refused"][1],
}
DOCTOR_TEXTS["too_many_attempts"] = (
    "محاولات كتير. استنى ١٥ دقيقة وجرّب تاني",
    "Too many attempts. Wait 15 minutes and try again",
)
STRINGS["doctor.too_many_attempts"] = {
    "ar": DOCTOR_TEXTS["too_many_attempts"][0],
    "en": DOCTOR_TEXTS["too_many_attempts"][1],
}
DOCTOR_TEXTS["check_fields"] = (
    "راجع: ",
    "Check: ",
)
STRINGS["doctor.check_fields"] = {
    "ar": DOCTOR_TEXTS["check_fields"][0],
    "en": DOCTOR_TEXTS["check_fields"][1],
}
DOCTOR_TEXTS["on_way_arrival"] = (
    "في الطريق من {time} · يوصل حوالي {arrival}",
    "On the way since {time} · arrives about {arrival}",
)
STRINGS["doctor.on_way_arrival"] = {
    "ar": DOCTOR_TEXTS["on_way_arrival"][0],
    "en": DOCTOR_TEXTS["on_way_arrival"][1],
}
DOCTOR_TEXTS["telegram_demo"] = (
    "في النسخة التجريبية رسايل تليجرام بتظهر هنا على الشاشة.",
    "In the demo, Telegram messages appear on screen.",
)
STRINGS["doctor.telegram_demo"] = {
    "ar": DOCTOR_TEXTS["telegram_demo"][0],
    "en": DOCTOR_TEXTS["telegram_demo"][1],
}
DOCTOR_TEXTS["telegram_launch"] = (
    "افتح تليجرام",
    "Open Telegram",
)
STRINGS["doctor.telegram_launch"] = {
    "ar": DOCTOR_TEXTS["telegram_launch"][0],
    "en": DOCTOR_TEXTS["telegram_launch"][1],
}
DOCTOR_TEXTS["telegram_fallback"] = (
    "لو ما اتفتحش، اضغط الزرار.",
    "If it did not open, press the button.",
)
STRINGS["doctor.telegram_fallback"] = {
    "ar": DOCTOR_TEXTS["telegram_fallback"][0],
    "en": DOCTOR_TEXTS["telegram_fallback"][1],
}
SIGNUP_TEXTS["why_telegram"] = (
    (
        "ليه تليجرام؟ نوا بيبعتلك عليه كود الدخول وتقرير الليلة. الزرار بيفتح البوت، وبتشارك "
        "رقمك مرة واحدة عشان نتأكد إنه تليفونك."
    ),
    (
        "Why Telegram? Nowa sends your login code and the evening report there. The button "
        "opens the bot; you share your number once so we know it is your phone."
    ),
)
STRINGS["signup.why_telegram"] = {
    "ar": SIGNUP_TEXTS["why_telegram"][0],
    "en": SIGNUP_TEXTS["why_telegram"][1],
}
SIGNUP_TEXTS["too_many_attempts"] = (
    "محاولات كتير. استنى ١٥ دقيقة وجرّب تاني",
    "Too many attempts. Wait 15 minutes and try again",
)
STRINGS["signup.too_many_attempts"] = {
    "ar": SIGNUP_TEXTS["too_many_attempts"][0],
    "en": SIGNUP_TEXTS["too_many_attempts"][1],
}
SIGNUP_TEXTS["check_fields"] = (
    "راجع: ",
    "Check: ",
)
STRINGS["signup.check_fields"] = {
    "ar": SIGNUP_TEXTS["check_fields"][0],
    "en": SIGNUP_TEXTS["check_fields"][1],
}
UI_TEXTS["doctor_on_way"] = (
    "الدكتور في الطريق · يوصل حوالي {time} · باقي {left} د",
    "Doctor on the way · arrives about {time} · {left} min left",
)
STRINGS["ui.doctor_on_way"] = {
    "ar": UI_TEXTS["doctor_on_way"][0],
    "en": UI_TEXTS["doctor_on_way"][1],
}
UI_TEXTS["copy"] = (
    "انسخ",
    "Copy",
)
STRINGS["ui.copy"] = {
    "ar": UI_TEXTS["copy"][0],
    "en": UI_TEXTS["copy"][1],
}
UI_TEXTS["copied"] = (
    "اتنسخ",
    "Copied",
)
STRINGS["ui.copied"] = {
    "ar": UI_TEXTS["copied"][0],
    "en": UI_TEXTS["copied"][1],
}
UI_TEXTS["copy_here"] = (
    "انسخ من هنا",
    "Copy from here",
)
STRINGS["ui.copy_here"] = {
    "ar": UI_TEXTS["copy_here"][0],
    "en": UI_TEXTS["copy_here"][1],
}
UI_TEXTS["mobile"] = (
    "رقم الموبايل",
    "Mobile number",
)
STRINGS["ui.mobile"] = {
    "ar": UI_TEXTS["mobile"][0],
    "en": UI_TEXTS["mobile"][1],
}
UI_TEXTS["password"] = (
    "كلمة السر",
    "Password",
)
STRINGS["ui.password"] = {
    "ar": UI_TEXTS["password"][0],
    "en": UI_TEXTS["password"][1],
}

STRINGS["chat.too_many_attempts"] = {
    "ar": DOCTOR_TEXTS["too_many_attempts"][0],
    "en": DOCTOR_TEXTS["too_many_attempts"][1],
    "franco": "Mo7awlat kteer. Estanna 15 de2ee2a w garrab tany",
}
STRINGS["chat.check_fields"] = {
    "ar": DOCTOR_TEXTS["check_fields"][0],
    "en": DOCTOR_TEXTS["check_fields"][1],
    "franco": "Rage3: ",
}
for _key in ("too_many_attempts", "check_fields"):
    DEMO_TEXTS[_key] = DOCTOR_TEXTS[_key]
    STRINGS["demo." + _key] = STRINGS["doctor." + _key].copy()

# Shared feedback accepts these label dictionaries too. Refusal remains generic
# outside doctor login, preserving the existing signup/chat request-error wording.
for _namespace, _catalog in (("signup", SIGNUP_TEXTS), ("demo", DEMO_TEXTS)):
    _catalog["login_refused"] = _catalog["error"]
    STRINGS[_namespace + ".login_refused"] = STRINGS[_namespace + ".error"]
STRINGS["chat.login_refused"] = STRINGS["chat.error"]

# patient and public presentation.
for _key, _values in {
    "call_emergency": ("اتصل بـ 123", "Call 123", "Ettesel be 123"),
    "edit": ("عدّل", "Edit", "3addel"),
    "edit_pick": ("عايز تعدّل إيه؟", "What would you like to edit?", "3ayez te3addel eh?"),
    "edit_name": ("الاسم", "Name", "El esm"),
    "edit_phone": ("الموبايل", "Mobile", "El mobile"),
    "edit_day": ("اليوم", "Day", "El yom"),
    "edit_area_text": ("المنطقة", "Area", "El mante2a"),
    "faq_label": ("أسئلة عن العيادة", "Clinic questions", "As2ela 3an el 3eyada"),
    "back_demo": ("رجوع للعرض", "Back to the demo", "Regoo3 lel 3ard"),
    "title": ("شات العيادة · نوا", "Clinic chat · Nowa", "Clinic chat · Nowa"),
    "switch_language": ("English", "العربية", "العربية"),
    "phone_label": ("تليجرام المريض", "Patient Telegram", "Telegram el mareed"),
}.items():
    STRINGS["chat." + _key] = dict(zip(("ar", "en", "franco"), _values, strict=True))
_add("book_again", "احجز تاني", "Book again", "E7gez tany")
_add("back", "رجوع للرئيسية", "Back to home", "Regoo3 lel ra2iseya")
_add("error_title", "الصفحة مش متاحة", "Page unavailable", "El saf7a mesh mota7a")
_add("journey_progress", "استعدادك للوصول", "Your journey", "Este3dadak lel wosool")
STRINGS["patient.leave_number"] = STRINGS["patient.your_turn"]
for _family in ("patient", "doctor"):
    STRINGS[_family + ".seen"]["ar"] = "اتكشف"
    STRINGS[_family + ".in_room"]["ar"] = "في الكشف"
UI_TEXTS.update(
    {
        "doctor_avatar": ("د", "D"),
        "page_front": ("نظّم انتظار عيادتك", "Organise your waiting room"),
        "page_demo": ("جرّب نوا", "Try Nowa"),
        "page_book": ("احجز كمريض", "Book as a patient"),
        "page_evening": ("عرض ليلة العيادة", "An evening at the clinic"),
        "page_start": ("افتح عيادتك", "Open your clinic"),
        "page_judge": ("دخول لجنة التحكيم", "Judge entry"),
    }
)
for _key, _pair in list(UI_TEXTS.items()):
    if _key.startswith("story_") and _key.endswith("_text"):
        UI_TEXTS[_key] = (_pair[0].rstrip(".") + ".", _pair[1].rstrip(".") + ".")
for _key, (_ar, _en) in UI_TEXTS.items():
    STRINGS["ui." + _key] = {"ar": _ar, "en": _en}
# display digits, including copy and prices, are Western.
for _key, _texts in STRINGS.items():
    if not _key.startswith(("patient.", "chat.", "ui.", "demo.")):
        continue
    for _lang, _value in _texts.items():
        _texts[_lang] = _value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))

STRINGS["doctor.who_first"] = {"ar": "مين يدخل؟", "en": "Who comes in?"}

STRINGS["source.health_information"] = {
    "ar": "معلومات صحية",
    "en": "Health information",
    "franco": "Ma3loomat se7eya",
}
STRINGS["source.high_blood_pressure"] = {
    "ar": "ضغط الدم المرتفع",
    "en": "High blood pressure",
    "franco": "Daght el dam el mortafe3",
}

STRINGS["identity.doctor"] = {"ar": "د. {name}", "en": "Dr. {name}", "franco": "Dr. {name}"}


def doctor_label(name: str, lang: str) -> str:
    return STRINGS["identity.doctor"][lang].format(name=name)


UI_TEXTS.update({"time_am": ("ص", "AM"), "time_pm": ("م", "PM")})
for _key in ("time_am", "time_pm"):
    STRINGS["ui." + _key] = dict(zip(("ar", "en"), UI_TEXTS[_key], strict=True))

DEMO_TEXTS["call_emergency"] = (
    STRINGS["chat.call_emergency"]["ar"],
    STRINGS["chat.call_emergency"]["en"],
)

UI_TEXTS["brand"] = (STRINGS["patient.brand"]["ar"], STRINGS["patient.brand"]["en"])
STRINGS["ui.brand"] = dict(zip(("ar", "en"), UI_TEXTS["brand"], strict=True))
DOCTOR_TEXTS["who_first"] = ("مين يدخل؟", "Who comes in?")

for _key, _ar, _en in (
    ("front_time_2043", "8:43 م", "8:43 PM"),
    ("front_time_1420", "2:20 م", "2:20 PM"),
    ("front_time_1910", "19:10", "19:10"),
    ("front_time_1905", "19:05", "19:05"),
    ("front_time_0820", "8:20 م", "8:20 PM"),
    ("front_time_0700", "19:00", "19:00"),
):
    UI_TEXTS[_key] = (_ar, _en)
    STRINGS["ui." + _key] = {"ar": _ar, "en": _en}

# all doctor/signup presentation copy lives here.
_AUDIT_DOCTOR = {
    "board_eyebrow": ("لوحة العيادة", "Clinic board"),
    "undo_empty": ("مفيش ضغطة تتراجع عنها", "No tap to undo"),
    "empty_bookings": ("مفيش حجوزات لسه", "No bookings yet"),
    "empty_questions": ("مفيش أسئلة", "No questions"),
    "later_group": ("بعدين", "Later"),
    "q_answer": ("جاوب", "Answer"),
    "q_save": ("احفظ للكل", "Save for everyone"),
    "q_later": ("بعدين", "Later"),
    "q_dismiss": ("تجاهل", "Dismiss"),
    "q_answer_prompt": (
        "اكتب إجابتك، وبعدها راجعها واحفظها للكل.",
        "Write your answer, then review and save it for everyone.",
    ),
    "q_saved": ("اتحفظت الإجابة للكل.", "The answer was saved for everyone."),
    "q_deferred": ("السؤال اتنقل لبعدين.", "The question was moved to Later."),
    "q_dismissed": ("السؤال اتقفل.", "The question was dismissed."),
    "q_draft_ready": (
        "الإجابة جاهزة. راجعها واحفظها للكل.",
        "Your draft is ready. Review and save it for everyone.",
    ),
    "cancel_day": ("إلغاء عيادة {day}", "Cancel the clinic on {day}"),
    "cancel_confirm": (
        "إلغاء العيادة؟ عندك {count} حجوزات نشطة.",
        "Cancel this clinic? You have {count} active bookings.",
    ),
    "keep_open": ("لسه، ارجع للوحة", "Keep open"),
    "close_confirm": ("تأكيد نهاية العيادة؟", "Finish this clinic?"),
    "close": ("خلصت العيادة", "Finish clinic"),
    "lang": ("لغة اللوحة والرسايل", "Board and message language"),
    "address": ("عنوان العيادة بالعربي", "Clinic address in Arabic"),
    "address_en": ("العنوان بالإنجليزي (اختياري)", "Address in English (optional)"),
    "hours_order": (
        "ميعاد النهاية لازم يكون بعد البداية.",
        "The end time must be after the start.",
    ),
    "past_date": ("اختار النهارده أو يوم جاي.", "Choose today or a future date."),
    "required_field": ("كمّل الحقل ده.", "Complete this field."),
    "invalid_field": ("راجع القيمة في الحقل ده.", "Check this field’s value."),
    "limit_counter": ("{count} / {limit} حرف", "{count} / {limit} characters"),
    "wrong_code": ("الكود غلط. فاضل {count} محاولات.", "Wrong code. {count} attempts left."),
    "reset_complete": ("كلمة السر اتغيرت.", "Your password was changed."),
    "source_label": ("المصدر: {source}", "Source: {source}"),
    "report_booked": ("محجوزين", "Booked"),
    "report_seen": ("اتكشفوا من المحجوزين", "Seen, of the booked"),
    "report_cancelled": ("اتلغوا", "Cancelled"),
    "report_close_cancelled": ("اتلغوا عند القفل", "Cancelled at close"),
    "report_no_show": ("ما جوش", "Did not come"),
    "report_walk_ins": ("جم من غير حجز واتكشفوا", "Came without a booking, seen"),
    "report_total": ("إجمالي الكشوفات", "Total seen"),
    "report_arrival": ("وصلت", "You arrived"),
    "report_start": ("بداية العيادة", "Clinic start"),
    "report_avg_visit": ("متوسط الكشف", "Average visit (min)"),
    "report_avg_wait": ("متوسط انتظار المريض", "Average patient wait (min)"),
    "report_failed": ("ما وصلتلوش الرسالة", "Messages that failed"),
    "switch_language": ("English", "العربية"),
    "mobile_placeholder": ("01xxxxxxxxx", "01xxxxxxxxx"),
}
for _key, _pair in _AUDIT_DOCTOR.items():
    DOCTOR_TEXTS[_key] = _pair
    STRINGS["doctor." + _key] = dict(zip(("ar", "en"), _pair, strict=True))
_AUDIT_SIGNUP = {
    key: _AUDIT_DOCTOR[key]
    for key in (
        "required_field",
        "invalid_field",
        "hours_order",
        "limit_counter",
        "address",
        "address_en",
    )
}
_AUDIT_SIGNUP.update(
    {
        "invalid_mobile": ("اكتب رقم موبايل مصري صحيح.", "Enter a valid Egyptian mobile number."),
        "wrong_code": (
            "الكود غلط أو انتهت صلاحيته. راجعه وجرب تاني.",
            "The code is wrong or expired. Check it and try again.",
        ),
        "no_working_days": ("اختار يوم شغل واحد على الأقل.", "Choose at least one working day."),
        "back_board": ("رجوع للوحة", "Back to the board"),
        "phone_complete": (
            "الحساب اتفعل وعيادتك جاهزة.",
            "Your account is verified and your clinic is ready.",
        ),
        "qr_alt": ("كود حجز العيادة", "Clinic booking QR code"),
    }
)
for _key, _pair in _AUDIT_SIGNUP.items():
    SIGNUP_TEXTS[_key] = _pair
    STRINGS["signup." + _key] = dict(zip(("ar", "en"), _pair, strict=True))
STRINGS["identity.clinic"] = {"ar": "عيادة د. {name}", "en": "Dr. {name}’s clinic"}
DEMO_TEXTS["sent_in_arabic"] = ("اتبعتت بالعربي", "Sent in Arabic")
STRINGS["demo.sent_in_arabic"] = dict(zip(("ar", "en"), DEMO_TEXTS["sent_in_arabic"], strict=True))


def health_question_count(count: int, lang: str) -> str:
    if lang == "ar":
        if count == 1:
            return "1 سؤال صحي"
        if count == 2:
            return "2 سؤالين صحيين"
        return f"{count} " + ("أسئلة صحية" if 3 <= count <= 10 else "سؤال صحي")
    return f"{count} health " + ("question" if count == 1 else "questions")


def health_source_label(title: str, url: str | None, lang: str) -> str:
    from nowa.library.source_display import source_link

    return source_link(url or "", title, lang).label


UI_TEXTS["sent_in_arabic"] = DEMO_TEXTS["sent_in_arabic"]
STRINGS["ui.sent_in_arabic"] = STRINGS["demo.sent_in_arabic"]
for _key in ("required_field", "invalid_field", "hours_order", "limit_counter"):
    DEMO_TEXTS[_key] = _AUDIT_DOCTOR[_key]
    STRINGS["demo." + _key] = STRINGS["doctor." + _key].copy()
    STRINGS["chat." + _key] = dict(STRINGS["doctor." + _key], franco=_AUDIT_DOCTOR[_key][1])


for _key, _pair in {
    "learned_title": ("اللي نوا اتعلمه من عيادتك", "What Nowa has learned from your clinic"),
    "learned_visit": ("مدة الكشف", "Visit length"),
    "learned_gap": ("الوقت قبل أول كشف", "Start gap"),
    "learned_no_show": ("نسبة اللي ما جاش", "No-show rate"),
    "learned_visit_value": ("{value} {minutes} · {n} {visits}", "{value} {minutes} · {n} {visits}"),
    "learned_gap_value": (
        "{value} {minutes} · {n} {evenings}",
        "{value} {minutes} · {n} {evenings}",
    ),
    "learned_no_show_value": ("{value}% · {n} {evenings}", "{value}% · {n} {evenings}"),
    # Arabic counts 3 to 10 take the plural noun; 1, 2 and 11 and more take the singular.
    "unit_minutes_few": ("دقايق", "minutes"),
    "unit_minutes_many": ("دقيقة", "minutes"),
    "unit_evenings_few": ("ليالي", "evenings"),
    "unit_evenings_many": ("ليلة", "evenings"),
    "unit_visits_few": ("كشوفات", "visits"),
    "unit_visits_many": ("كشف", "visits"),
    "still_learning": ("لسه بيتعلم", "still learning"),
}.items():
    DOCTOR_TEXTS[_key] = _pair
    STRINGS["doctor." + _key] = dict(zip(("ar", "en"), _pair, strict=True))

# patient message text is PENDING in messaging.templates.
STRINGS["message.standby_offer"] = {
    "ar": (
        "{patient_name}: فضي مكان عند {doctor_name} يوم {day}، معادك المتوقع "
        "{expected_time}. خده من هنا: {take_link} المكان محجوزلك 20 دقيقة بس."
    ),
    "en": (
        "{patient_name}: a place with {doctor_name} is available on {day}, expected"
        " time {expected_time}. Take it here: {take_link} This offer is valid for "
        "20 minutes."
    ),
    "franco": (
        "{patient_name}: fi makan fedi ma3 {doctor_name} yom {day}, el ma3ad el "
        "motawaqqa3 {expected_time}. Khodo men hena: {take_link} El da3wa sal7a 20 "
        "de2i2a."
    ),
}
STRINGS["message.standby_closed"] = {
    "ar": (
        "{patient_name}: عيادة {doctor_name} يوم {day} خلصت ومفيش مكان فضي. "
        "احجز أقرب يوم فاضي من هنا: {next_day_link}"
    ),
    "en": (
        "{patient_name}: {doctor_name}’s clinic on {day} has closed and the standby"
        " list has ended. Book the next open day: {next_day_link}"
    ),
    "franco": (
        "{patient_name}: 3eyadet {doctor_name} yom {day} khelsit we qaymet el "
        "entezar et2aflet. E7gez a2rab yom fadi: {next_day_link}"
    ),
}
for _key, _pair in {
    "standby_join": ("حطني في قايمة الانتظار", "Join the standby list"),
    "standby_confirm": ("تأكيد قايمة الانتظار", "Confirm standby request"),
    "standby_joined": (
        "رقمك {position} في قايمة الانتظار. لو مكان فضي هبعتلك على تليجرام.",
        (
            "You are number {position} on the standby list. If a place opens, I will "
            "message you on Telegram."
        ),
    ),
    "standby_duplicate": (
        "إنت في القايمة خلاص، رقمك {position}.",
        "You are already on the list, at position {position}.",
    ),
    "standby_link": (
        "اربط تليجرام الأول عشان نكمل قايمة الانتظار ونبعتلك لو مكان فضي.",
        (
            "Link Telegram first to finish joining the standby list and receive an "
            "offer if a place opens."
        ),
    ),
    "standby_check": ("ربطت تليجرام", "I have linked Telegram"),
    "standby_full": (
        "اليوم ده مليان. تقدر تدخل قايمة الانتظار أو تختار يوم تاني.",
        "That day is full. You can join the standby list or choose another day.",
    ),
}.items():
    STRINGS["chat." + _key] = {"ar": _pair[0], "en": _pair[1], "franco": _pair[1]}
for _key, _pair in {
    "standby_title": ("دعوة من قايمة الانتظار", "Standby offer"),
    "standby_take": ("خد المكان", "Take this place"),
    "standby_decline": ("مش هقدر أجي", "Decline this offer"),
    "standby_expired": (
        "الدعوة انتهت والمكان راح لحد تاني. تقدر تحجز أقرب يوم فاضي.",
        "This offer has ended and the place has passed on. You can book the next open day.",
    ),
    "standby_taken": (
        "حجزك اتأكد. التفاصيل هتوصلك على تليجرام.",
        "Your booking is confirmed. The details will reach you on Telegram.",
    ),
    "standby_valid": ("المكان محجوزلك 20 دقيقة بس.", "This offer is valid for 20 minutes."),
}.items():
    STRINGS["patient." + _key] = {"ar": _pair[0], "en": _pair[1], "franco": _pair[1]}
for _key, _pair in {
    "standby_count": ("{count} في قايمة الانتظار", "{count} on the standby list"),
    "report_standby_taken": ("حجزوا من قايمة الانتظار", "Bookings taken from standby"),
}.items():
    DOCTOR_TEXTS[_key] = _pair
    STRINGS["doctor." + _key] = dict(zip(("ar", "en"), _pair, strict=True))

STRINGS["chat.standby_unavailable"] = {
    "ar": "ربط تليجرام مش متاح دلوقتي. كلم العيادة أو اختار يوم تاني.",
    "en": "Telegram linking is unavailable right now. Contact the clinic or choose another day.",
    "franco": "Rabt Telegram mesh mota7 delwa2ti. Kallem el 3eyada aw ekhtar yom tani.",
}

DOCTOR_TEXTS["standby_number"] = ("انتظار {number}", "standby {number}")
STRINGS["doctor.standby_number"] = {
    "ar": "انتظار {number}",
    "en": "standby {number}",
    "franco": "standby {number}",
}

for _key, _pair in {
    "standby_offer": ("مكان متاح من قايمة الانتظار", "Standby place offered"),
    "standby_closed": ("قايمة الانتظار اتقفلت", "Standby list closed"),
}.items():
    MESSAGE_LABELS["op:" + _key] = "message_" + _key
    UI_TEXTS["message_" + _key] = _pair
    STRINGS["ui.message_" + _key] = dict(zip(("ar", "en"), _pair, strict=True))


# shared linking presentation; no patient or phone values in copy.
LINKING_TEXTS = {
    "telegram_scan": (
        "امسح الكود بتليفونك، تليجرام هيفتح على البوت",
        "Scan the code with your phone to open the bot in Telegram.",
        "Emsa7 el code be telephonek, Telegram hayefta7 3ala el bot.",
    ),
    "telegram_install": (
        "لو مفيش تليجرام، اللينك هيوديك تنزّله",
        "If you do not have Telegram, the link takes you to download it.",
        "Law mafeesh Telegram, el link haywadeek tenazzelo.",
    ),
    "telegram_renew": ("جدّد اللينك", "Renew the link", "Gadded el link"),
    "telegram_edit": ("عدّل الموبايل", "Edit the mobile", "3addel el mobile"),
    "telegram_linked": (
        "اتربط، ارجع للصفحة وكمل بالكود اللي وصلك",
        "Linked. Return to the page and continue with the code you received.",
        "Et rabat. Erga3 lel page w kammel bel code elly weselak.",
    ),
    "telegram_patient_linked": ("تليجرام اتربط", "Telegram linked", "Telegram et rabat"),
    "telegram_mismatch": TELEGRAM_TEXTS["contact_mismatch"],
    "telegram_retry": ("حاول تاني", "Try again", "7awel tany"),
    "telegram_error": (
        "مش قادر أتأكد من الربط دلوقتي. حاول تاني.",
        "Unable to check the link right now. Try again.",
        "Mesh ader at2akked men el rabt delwa2ty. 7awel tany.",
    ),
}
for _key, _values in LINKING_TEXTS.items():
    for _prefix in ("patient", "chat", "signup"):
        STRINGS[_prefix + "." + _key] = dict(zip(("ar", "en", "franco"), _values))
    SIGNUP_TEXTS[_key] = _values[:2]
