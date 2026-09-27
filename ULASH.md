# Yangi dasturni (startapni) Obuna Admin'ga ulash

Namuna — EproPos (`ndoston1202-glitch/salespos1`, `server.py` dagi "obuna" bo'limi).

## 1. Obuna Admin'da
**Sozlamalar → Dasturlar** → yangi dastur: nomi (masalan `EproCafe`) va **kodi** (masalan `eprocafe`). Kod o'zgarmaydi.

## 2. Dasturingizda
1. `obuna.py` faylini dasturingizga nusxalang (bog'liqliksiz, sof Python).
2. **Mijoz ID** — har bir o'rnatishning noyob 12 belgili raqami (masalan tasodifiy hex, bir marta yaratilib saqlanadi):
   `obuna.normalize_shop_id(secrets.token_hex(6))` → `1A2B-3C4D-5E6F`. Uni "Obuna" sahifasida ko'rsating.
3. Kodni tekshirish:
   ```python
   info = obuna.read_code(kod, ishonchli_kalit)   # imzo noto'g'ri bo'lsa ValueError
   assert info["s"] == mijoz_id                   # boshqa mijozning kodi emas
   assert info.get("a") in (None, "", "eprocafe") # boshqa dasturning kodi emas
   muddat = info["u"]                             # "YYYY-MM-DD" - shu sanagacha ishlaydi
   ```
   `ishonchli_kalit` — Obuna Admin → Sozlamalar → **Ochiq kalit** (`obuna.key_from_text("...")`).
   Kodga yana: `n` sotuvchi nomi, `p` telefon (bloklangan ekranda "to'lov uchun murojaat" sifatida), `r` = davom ettirish kodi.
4. Muddat tugaganda dasturni bloklang (ma'lumotlarni o'chirmang) va kod kiritish joyini qoldiring.
   Soatni orqaga qo'yishdan himoya: ko'rilgan eng katta sanani saqlang.
5. Vaqtincha to'xtatish (ixtiyoriy, internet kerak): har 30 daqiqada
   `https://ntfy.sh/<obuna.status_topic(ochiq_kalit)>/json?poll=1&since=all` ni o'qing, har bir xabarning `message`
   maydonini `obuna.read_status(message, ochiq_kalit)` bilan tekshiring; eng katta `ts` li ro'yxatda (`x`) mijoz ID bo'lsa —
   to'xtatilgan, bo'lmasa — ishlaydi. Eski (`ts` kichik) xabarlarni e'tiborsiz qoldiring.

EproPos'dagi tayyor kod: `license_state`, `license_activate`, `check_vendor_status` funksiyalari.
