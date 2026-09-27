# 🔑 Obuna Admin

Dasturlaringiz (EproPos va kelajakdagi boshqa startaplar) **oylik obunalarini** boshqarish paneli.
Faqat sizning kompyuteringizda ishlaydi — server shart emas. **Faqat Python 3.8+ kerak.**

## Ishga tushirish
- Windows: **OBUNA_ADMIN.bat** ga ikki marta bosing → brauzerda `http://127.0.0.1:8200` ochiladi
- Linux/macOS: `python3 admin.py`

## Imkoniyatlar
- **Dasturlar** — har bir startap alohida (nomi va kodi, masalan `epropos`). Bir dastur uchun berilgan kod boshqasida ishlamaydi
- **Mijozlar** (biznes egalari): dastur, biznes nomi, egasi, telefon, manzil, **Mijoz ID**, oylik narx, izoh
- **Demo muddati** — yangi mijoz qo'shishda o'zingiz belgilaysiz (3/7/14/30 kun yoki sana), demo kodi darhol chiqadi
- **To'lov qabul qilish** — 1/2/3/6/12 oy: muddat uzaytiriladi, faollashtirish kodi chiqadi →
  "Telegram'da yuborish" yoki nusxa olish
- **To'lovsiz kod** — sinov, bepul davr yoki o'zingizning do'koningiz uchun
- **⏸ Vaqtincha to'xtatish / ▶️ Davom ettirish** — mijozning dasturi internetga ulanganda (30 daqiqagacha) bloklanadi/ochiladi.
  Internetsiz mijoz uchun "davom ettirish kodi" beriladi
- **Bosh sahifa** — dasturlar bo'yicha mijozlar va tushum, faol / tugayotgan / muddati o'tgan / to'xtatilgan mijozlar
- **Zaxira nusxa** — ma'lumotlar va maxfiy kalit bitta faylda

## ⚠️ Maxfiy kalit
Kodlar raqamli imzo (Ed25519) bilan imzolanadi — ularni faqat sizning kompyuteringizdagi **maxfiy kalit** yarata oladi.
Kalit va ma'lumotlar: `%APPDATA%\ObunaAdmin` (avvalgi versiyadan qolgan bo'lsa `%APPDATA%\EproPosAdmin`).
**Sozlamalar → Zaxira nusxa** ni flesh yoki bulutda saqlang va hech kimga bermang. Kalit repoga hech qachon yuklanmaydi.

## Yangi startapni ulash
[ULASH.md](ULASH.md) — yangi dasturingizga obuna tekshiruvini qo'shish yo'riqnomasi (EproPos namunasida).

## Fayllar
| Fayl | Vazifasi |
|------|----------|
| `admin.py` | Panel serveri (Python standart kutubxonasi) |
| `obuna.py` | Imzo va kodlar kutubxonasi — **dasturlaringiz ichiga ham shu fayl qo'yiladi** |
| `static/` | Panel sahifasi |
| `tests/` | `python -m unittest discover tests` |
