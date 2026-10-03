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
    "الأرقام مش صحيحة، جرّب تاني",
    "Those digits did not match. Try again",
    "El arkam mesh sa7, garrab tany",
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
    "login_sub": ("عيادة النهارده، الإعدادات، والتقرير", "Tonight's clinic, settings and report"),
    "create_clinic": ("لسه معندكش عيادة؟ اعمل واحدة", "No clinic yet? Create one"),
    "booked_count": ("محجوز", "Booked"),
    "seen_count": ("خلصوا", "Completed"),
    "remaining_count": ("لسه", "Remaining"),
    "in_room": ("جوه دلوقتي", "In the room now"),
    "who_next": ("مين يدخل بعده؟", "Who comes in next?"),
    "all_queue": ("الطابور كله", "Full queue"),
    "clinic_link": ("لينك عيادتك", "Your clinic link"),
    "timing_title": ("توقيت وصول المرضى", "Patient arrival timing"),
    "brand": ("نوا", "Nowa"),
    "login": ("دخول الدكتور", "Doctor login"),
    "mobile": ("رقم الموبايل", "Mobile number"),
    "password": ("كلمة السر", "Password"),
    "reset": ("نسيت كلمة السر", "Forgot password"),
    "request_code": ("ابعت كود التغيير", "Send reset code"),
    "code": ("الكود (٦ أرقام)", "Code (6 digits)"),
    "new_password": (
        "كلمة السر الجديدة (٨ حروف على الأقل)",
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
    "q_already_done": ("السؤال ده اتخلص", "This question is already done"),
    "q_text_only": (
        "اكتب إجابة نصية من ١ إلى ١٠٠٠ حرف",
        "Write a text answer of 1 to 1000 characters",
    ),
    "settings": ("إعدادات العيادة", "Clinic settings"),
    "logout": ("خروج", "Log out"),
    "no_evening": ("مفيش عيادة الليلة", "No evening tonight"),
    "on_way": ("أنا في الطريق", "I'm on my way"),
    "walk_in": ("من غير حجز", "Walk-in"),
    "undo": ("تراجع عن آخر ضغطة", "Undo last tap"),
    "close": ("خلصت الليلة", "Done for tonight"),
    "cancel": ("إلغاء عيادة الليلة", "Cancel tonight"),
    "close_confirm": ("تأكيد نهاية الليلة؟", "Finish tonight?"),
    "close_untold": (
        "{count} مرضى لسه ما اتطلبوش، هتوصلهم رسالة إلغاء مع لينك لحجز يوم تاني. تأكيد؟",
        "{count} patients were not called yet, they will get a cancel message "
        "with a rebook link. Confirm?",
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
        "التغيير ده يلغي يوم عليه حجوزات أو ينهيه قبل معاد مريض",
        "This change removes a booked day or ends it before a patient's expected time",
    ),
    "silent": ("لسه ما أكدش التحرك", "Has not confirmed leaving"),
    "booked": ("محجوز", "Booked"),
    "told_to_leave": ("اتطلب يتحرك", "Called to leave"),
    "on_my_way": ("في الطريق", "On my way"),
    "seen": ("الكشف تم", "Seen"),
    "cancelled": ("اتلغى", "Cancelled"),
    "didnt_come": ("ما جاش", "Did not come"),
    "hours": ("مواعيد الأسبوع", "Weekly hours"),
    "weekday": ("اليوم", "Day"),
    "start": ("البداية", "Start"),
    "end": ("النهاية", "End"),
    "enabled": ("فيه عيادة", "Open"),
    "override": ("ميعاد يوم معين", "Day override"),
    "date": ("التاريخ", "Date"),
    "closed": ("مقفول", "Closed"),
    "delete_override": ("امسح ميعاد اليوم", "Delete override"),
    "usual_visit_min": ("مدة الكشف المعتادة بالدقايق", "Usual visit minutes"),
    "cushion_min": ("هامش الوصول بالدقايق", "Arrival cushion minutes"),
    "safe_drive_min": ("مدة الطريق الاحتياطية بالدقايق", "Safe drive minutes"),
    "max_per_evening": ("أقصى عدد حجوزات (فاضي = من غير حد)", "Maximum bookings (empty = off)"),
    "info": ("معلومات صفحة العيادة", "Clinic page information"),
    "price": ("سعر الكشف", "Price"),
    "address": ("العنوان", "Address"),
    "what_to_bring": ("المريض يجيب إيه", "What to bring"),
    "other": ("معلومات تانية", "Other information"),
    "lang": ("لغة الدكتور", "Doctor language"),
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
for _key, (_ar, _en) in DOCTOR_TEXTS.items():
    STRINGS["doctor." + _key] = {"ar": _ar, "en": _en}


# APPROVED under Decision 048 and the contracts README UI-strings rule.
TELEGRAM_TEXTS = {
    "share_contact": (
        "شارك رقمك عشان نتأكد إنه رقمك",
        "Share your number so we can confirm it is yours",
        "Share your number so we can confirm it is yours",
    ),
    "contact_mismatch": (
        "الرقم ده مش هو رقم الحجز/التسجيل",
        "That number does not match the booking or registration",
        "El ra2m da mesh ra2m el 7agz aw el tasgeel",
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
    "walkin": ("🚶 من غير حجز", "🚶 Walk-in", "🚶 Men gheir 7agz"),
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
        "أهلاً، أنا نوا، مساعد عيادة د. {name}",
        "Hello, I'm Nowa, Dr. {name}'s clinic assistant.",
        "Ahlan, ana Nowa, mosa3ed 3eyadet Dr. {name}.",
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
        "اكتب اسم المريض من فضلك.",
        "Please write the patient's name.",
        "Ekteb esm el mareed.",
    ),
    "phone_ask": (
        "اكتب رقم الموبايل للحجز من فضلك.",
        "Please write the booking mobile number.",
        "Ekteb ra2m el mobile lel 7agz.",
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
        "Eb3at esm el mareed w ra2m el mobile tany 3ashan nerage3 el 7agz.",
    ),
    "draft_replay_reask": (
        "لإكمال الحجز ابعت الاسم ورقم الموبايل تاني.",
        "To continue booking, send the name and mobile again.",
        "3ashan nekammel el 7agz, eb3at el esm w ra2m el mobile tany.",
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
        "ما لقيناش حجز بالبيانات دي.",
        "No booking matched those details.",
        "Ma la2enash 7agz bel bayanat dy.",
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
    "location": ("موقعي الحالي", "My current location", "Mawke3y el 7aly"),
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
        "7agzak yom {day}, ra2mak {number}, 7awaly {time}.",
    ),
    "status": (
        "{day}، رقم {number}، حوالي {time}، {status}",
        "{day}, number {number}, around {time}, {status}",
        "{day}, ra2m {number}, 7awaly {time}, {status}",
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
    "submit_lookup": ("شوف الحجز", "Find booking", "Shoof el 7agz"),
    "error": (
        "حصل خطأ. جرّب تاني.",
        "Something went wrong. Try again.",
        "7asal khata2. Garrab tany.",
    ),
    "location_error": (
        "اختار المنطقة من القايمة.",
        "Choose an area from the list.",
        "Ekhtar el mante2a men el kayma.",
    ),
}
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
    "area": ("أقرب منطقة (مكان تقريبي)", "Nearest area (rough pin)"),
    "locate": ("حدد المكان مرة واحدة", "Locate once"),
    "map_link": ("الصق لينك الخريطة", "Paste the map link"),
    "hours": ("أيام ومواعيد العيادة", "Clinic days and hours"),
    "mon": ("الاثنين", "Monday"),
    "tue": ("الثلاثاء", "Tuesday"),
    "wed": ("الأربعاء", "Wednesday"),
    "thu": ("الخميس", "Thursday"),
    "fri": ("الجمعة", "Friday"),
    "sat": ("السبت", "Saturday"),
    "sun": ("الأحد", "Sunday"),
    "enabled": ("العيادة شغالة", "Open"),
    "start": ("من", "From"),
    "end": ("لحد", "Until"),
    "price": ("سعر الكشف بالجنيه", "Visit price in EGP"),
    "clinic_phone": ("تليفون العيادة (اختياري)", "Clinic phone (optional)"),
    "password": ("كلمة السر (٨ حروف على الأقل)", "Password (at least 8 characters)"),
    "agreement": ("اتفاق الدكتور", "Doctor agreement"),
    "agree": ("قريت الاتفاق وبوافق عليه", "I have read and accept the agreement"),
    "complete": ("احفظ وافتح العيادة", "Save and open the clinic"),
    "sent": ("الكود اتبعت. اكتبه هنا.", "Code sent. Enter it here."),
    "error": (
        "ما قدرناش نكمل. راجع البيانات وجرب تاني.",
        "Could not complete. Check the details and try again.",
    ),
    "map_error": ("الصق اللينك الكامل أو اختار المنطقة", "paste the full link or pick the area"),
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
    "title": ("شاهد أمسية كاملة", "Watch a full evening"),
    "intro": (
        "عيادة ومرضى خياليون. نفس محرك الطابور والرسائل، بلا ذكاء اصطناعي. "
        "السفر ثابت حسب المنطقة. الأوقات والنتائج هنا محاكاة.",
        "Fictional clinic and patients. The real queue and message engine, with no AI. "
        "Travel is fixed by area. Times and results are simulated.",
    ),
    "play": ("تشغيل", "Play"),
    "pause": ("إيقاف مؤقت", "Pause"),
    "restart": ("أمسية جديدة", "New evening"),
    "speed": ("السرعة", "Speed"),
    "dashboard": ("لوحة الطبيب", "Doctor dashboard"),
    "report": ("تقرير الأمسية", "Evening report"),
    "queue": ("الطابور", "Queue"),
    "phones": ("هواتف الرسائل الخيالية (هاتف كريم أولاً)", "Drawn phones (Karim first)"),
    "timeline": ("سجل المحرك", "Engine timeline"),
    "travel": ("سفر الطبيب", "Doctor travel"),
    "minutes": ("دقيقة", "minutes"),
    "closed": ("انتهت الأمسية", "Evening closed"),
    "walkin": ("من غير حجز", "Walk-in"),
    "doctor": ("هاتف الطبيب", "Doctor phone"),
    "watch_error": (
        "تعذر إكمال العرض. جرّب أمسية جديدة.",
        "Could not continue. Start a new evening.",
    ),
    "public_book": ("جرّب الحجز من غير ذكاء اصطناعي", "Book without AI"),
    "start_booking": ("ابدأ حجز خيالي", "Start a fictional booking"),
    "banner": ("لو حالة طارئة اتصل بـ 123", "For an emergency call 123"),
    "patient_phone": ("هاتف المريض الخيالي", "Fictional patient phone"),
    "book_as": ("احجز باسم {name} (خيالي)", "Book as {name} (fictional)"),
    "area": ("اختار المنطقة", "Choose an area"),
    "area_other": ("مش في القايمة", "Not listed"),
    "confirm_intro": (
        "تأكيد الحجز والموافقة على النص الموضح فوق",
        "Confirm booking and agree to the consent above",
    ),
    "confirm": ("موافق، أكد الحجز", "I agree, confirm booking"),
    "change_day": ("اختار يوم تاني", "Choose another day"),
    "error": ("تعذر إكمال الطلب. جرّب تاني.", "Could not complete. Try again."),
    "phone_error": ("تعذر تحميل الهاتف الخيالي.", "Could not load the drawn phone."),
    "start_error": ("تعذر بدء الحجز. حدّث الصفحة.", "Could not start booking. Refresh the page."),
}
for _key, (_ar, _en) in DEMO_TEXTS.items():
    STRINGS["demo." + _key] = {"ar": _ar, "en": _en}
STRINGS["signup.public_book"] = STRINGS["demo.public_book"]

# Slice 14 presentation strings; no message-template or engine changes.
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
    "clinic_title": ("عيادة د. {name}", "Dr. {name}'s clinic", "3eyadet Dr. {name}"),
    "faq_price": ("سعر الكشف", "Price", "Se3r el kashf"),
    "faq_address": ("العنوان", "Address", "El 3enwan"),
    "faq_what_to_bring": ("أجيب معايا إيه؟", "What to bring?", "Ageeb ma3aya eh?"),
    "faq_other": ("معلومات تانية", "Other info", "Ma3lomat tanya"),
    "book_chip": ("احجز", "Book", "E7gez"),
    "book_text": ("عايز أحجز", "I want to book", "3ayez a7gez"),
}.items():
    STRINGS["chat." + _key] = dict(zip(("ar", "en", "franco"), _values, strict=True))

# Slice 16: approved v2 story copy, preserving the mockup inline number spans.
UI_TEXTS = {
    "front_nowa_waiting_room_agent": ("Nowa · waiting-room agent", "Nowa · waiting-room agent"),
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
    "front_how_it_works": ("How it works", "How it works"),
    "front_one_evening_three_moments": ("ليلة واحدة، تلات لحظات", "One evening, three moments"),
    "front_the_doctor_taps_twice_nowa_does_the": (
        "الدكتور بيضغط ضغطتين، ونوا بيعمل الباقي.",
        "The doctor taps twice; Nowa does the rest.",
    ),
    "front_sunday": ("الأحد ·", "Sunday ·"),
    "front_nowa_dr_hesham_s_clinic": ("نوا · عيادة د. هشام", "Nowa · Dr. Hesham's clinic"),
    "front_bot": ("بوت", "Bot"),
    "front_sun_4_oct": ("Sun, 4 Oct", "Sun, 4 Oct"),
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
        "Karim books his father and gets number 7",
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
    "front_for_the_doctor": ("For the doctor", "For the doctor"),
    "front_two_taps_all_evening": ("ضغطتين بس طول الليلة", "Two taps all evening"),
    "front_on_my_way_when_you_leave_who": (
        '"في الطريق" لما تتحرك، و"مين يدخل" بعد كل كشف. مفيش صالة زحمة ولا تليفونات للسكرتيرة.',
        '"On my way" when you leave, "who comes in" after each visit. '
        "No packed waiting room, no calls to the secretary.",
    ),
    "front_min": ("د", "min"),
    "front_for_the_patient": ("For the patient", "For the patient"),
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
        "switch_language": ("English", "Arabic"),
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
        "told_to_leave": ("اتطلب", "Called"),
        "on_my_way": ("في الطريق", "On the way"),
        "in_room": ("جوه", "In"),
        "seen": ("خلص", "Done"),
        "cancelled": ("اتلغى", "Cancelled"),
        "didnt_come": ("ما جاش", "Didn't come"),
        "walkin": ("من غير حجز", "Walk-in"),
        "doctor": ("الدكتور", "Doctor"),
        "number": ("رقم {n}", "number {n}"),
        "link_booking": ("افتح لينك الحجز", "Open booking link"),
        "link_way": ("أنا في الطريق", "I'm on my way"),
        "link_rebook": ("احجز يوم تاني", "Book another day"),
        "failed": ("ما وصلتش · الدكتور اتبلّغ", "Not delivered · doctor alerted"),
        "report_title": ("ليلة الثلاثاء في أرقام", "Tuesday evening in numbers"),
        "report_booked": ("الحجوزات", "Bookings"),
        "report_came": ("جم", "Came"),
        "report_no_show_count": ("ما جوش", "Didn't come"),
        "report_walk_ins": ("من غير حجز", "Walk-ins"),
        "report_avg_wait": ("متوسط الانتظار في العيادة (تقريبًا)", "Avg clinic wait (approx.)"),
        "with_nowa": ("مع نوا", "With Nowa"),
        "without_nowa": ("من غير نوا", "Without Nowa"),
        "baseline": ("229 د (محاكاة)", "229 min (simulated)"),
        "report_sub": (
            "الأرقام دي محاكاة على عيادة خيالية.",
            "Simulated numbers on a fictional clinic.",
        ),
        "watch_error": (
            "تعذر إكمال العرض. جرّب ليلة جديدة.",
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
            "{name} (number {n}) entered for a walk-in visit",
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
