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
    "new_sms",
    "تمام، لينك حجزك الجديد في رسالة SMS",
    "Done, your new link is in an SMS",
    "Tamam, link 7agzak el gedeed fe SMS",
)
_add(
    "cancelled_done",
    "تمام، حجزك اتلغى",
    "Done, your booking is cancelled",
    "Tamam, 7agzak et2alagha",
)
_add(
    "wait",
    "هنبعتلك رسالة لما ييجي وقت تتحرك",
    "We'll text you when to leave",
    "Hanb3atlak emta tet7arrak",
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
    "الطلب مش صالح. افتح لينك الرسالة تاني",
    "This request is invalid. Open your SMS link again",
    "Efta7 link el SMS tany",
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
        "لو الرقم مسجل، هيوصلك كود في رسالة",
        "If the number is registered, a code will arrive by message",
    ),
    "tonight": ("عيادة النهارده", "Tonight's clinic"),
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
        "افتح لينك تليجرام من رسالة SMS أو من لوحة الدكتور",
        "Open the Telegram link from your SMS or doctor dashboard",
        "Efta7 link Telegram men SMS aw lo7et el doctor",
    ),
    "bad_link": (
        "افتح اللينك من رسالة SMS تاني",
        "Open the link from your SMS again",
        "Efta7 link el SMS tany",
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
        "{patient} — د. {doctor}\n{day}، رقم {number}، المعاد المتوقع {time}",
        "{patient} — Dr. {doctor}\n{day}, number {number}, expected time {time}",
        "{patient} — Dr. {doctor}\n{day}, rakm {number}, el ma3ad {time}",
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
    "brand": ("نوا", "Nowa"),
    "headline": ("كل مريض يتحرك من البيت في وقته", "Each patient leaves home at the right time"),
    "intro": (
        "نوا بيظبط وقت وصول المرضى من مواعيد العيادة وحركة الطابور. "
        "ضغطة وانت في الطريق، وضغطة بعد كل كشف.",
        "Nowa times patient arrivals from your clinic hours and queue. "
        "Tap when you leave, then after each visit.",
    ),
    "signup": ("اعمل عيادتك", "Create your clinic"),
    "login": ("دخول الدكتور", "Doctor login"),
    "judge": ("كود لجنة التحكيم", "Judge code"),
    "judge_start": ("ابدأ عيادة تجريبية", "Start a practice clinic"),
    "watch": ("اتفرج على ليلة", "Watch an evening"),
    "mobile": ("موبايل الدكتور", "Doctor mobile"),
    "request_code": ("ابعت كود SMS", "Send SMS code"),
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
