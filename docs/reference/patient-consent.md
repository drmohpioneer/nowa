# Patient consent line (shown at booking, one tap)

Version: 0.1 (draft)

Code copies these texts exactly. `consents.version` stores "0.1"; `consents.text_hash` stores SHA-256 of the exact text shown in the patient's language. The privacy policy link is the clinic's /privacy page.

## Self (booking_for = self)
AR: بحجزك بتوافق إن نوّا تحفظ اسمك ورقمك ورسايلك عشان الحجز ده وتوصّلها للدكتور. سياسة الخصوصية: {privacy_link}
EN: By booking you agree that Nowa keeps your name, number and messages for this booking and shares them with the doctor. Privacy policy: {privacy_link}
Franco: Be 7agzak bet-wafe2 en Nowa te7faz esmak w ra2mak w rasaylak 3ashan el 7agz da w tewasalha lel doktor. Privacy policy: {privacy_link}

## Booking for someone else (booking_for = other, Decision 032)
AR: عندي إذن من الشخص ده إني أحجز له وأدّي بياناته لنوّا وللدكتور.
EN: I have this person's permission to book for them and to give their details to Nowa and the doctor.
Franco: 3andy ezn men el shakhs da eny a7gez lo w addy bayanato le Nowa w lel doktor.

## Button label
AR: موافق واحجز
EN: Agree and book
Franco: Mwafe2 w e7gez
