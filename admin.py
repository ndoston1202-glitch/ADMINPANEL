"""Obuna Admin - dasturlaringiz (EproPos va boshqa startaplar) obunalarini boshqarish paneli.

Mijozlar (biznes egalari), oylik obuna to'lovlari, demo muddati, faollashtirish kodlari va vaqtincha to'xtatish.
Faqat shu kompyuterda ishlaydi (http://127.0.0.1:8200). Ma'lumotlar va MAXFIY KALIT dastur papkasidan tashqarida:
Windows: %APPDATA%\\ObunaAdmin, boshqa tizimlar: ~/.obuna-admin. Maxfiy kalitni yo'qotmang - zaxira nusxa oling
(Sozlamalar -> Zaxira nusxa). Kalitsiz mavjud mijozlar uchun yangi kod yaratib bo'lmaydi."""

import io
import json
import mimetypes
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import obuna  # noqa: E402


def env(name, default=None):
    """OBUNA_* sozlamalari (eski EPROPOS_ADMIN_* nomlari ham ishlaydi)."""
    return os.environ.get("OBUNA_" + name) or os.environ.get("EPROPOS_ADMIN_" + name) or default


def default_data_dir():
    if os.environ.get("APPDATA"):
        old = os.path.join(os.environ["APPDATA"], "EproPosAdmin")  # avvalgi versiya shu yerda saqlagan
        return old if os.path.isdir(old) else os.path.join(os.environ["APPDATA"], "ObunaAdmin")
    old = os.path.join(os.path.expanduser("~"), ".epropos-admin")
    return old if os.path.isdir(old) else os.path.join(os.path.expanduser("~"), ".obuna-admin")


PORT = int(env("PORT", "8200"))
DATA_DIR = env("DATA") or default_data_dir()
DB_PATH = os.path.join(DATA_DIR, "admin.db")
KEY_PATH = os.path.join(DATA_DIR, "vendor.key")
STATIC = os.path.join(HERE, "static")
RELAY = (os.environ.get("OBUNA_RELAY") or os.environ.get("EPROPOS_RELAY") or "https://ntfy.sh").rstrip("/")
WARN_DAYS = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, app_id TEXT NOT NULL UNIQUE, note TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business TEXT NOT NULL, owner TEXT, phone TEXT, address TEXT, shop_id TEXT,
    tariff INTEGER NOT NULL DEFAULT 0, paid_until TEXT, note TEXT,
    created_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    amount INTEGER NOT NULL DEFAULT 0, months INTEGER NOT NULL DEFAULT 0,
    paid_at TEXT NOT NULL, until TEXT NOT NULL, code TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

lock = threading.Lock()
_web = urllib.request.build_opener()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def today():
    fake = env("TODAY")
    return date.fromisoformat(fake) if fake else date.today()


def now():
    return today().isoformat() + datetime.now().strftime(" %H:%M")


def add_months(d, months):
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    days = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(y, m, min(d.day, days[m - 1]))


def load_secret():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(KEY_PATH):
        with open(KEY_PATH, "w") as f:
            f.write(obuna.key_text(obuna.new_secret()))
    with open(KEY_PATH) as f:
        return obuna.key_from_text(f.read())


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(clients)")]
    if "suspended" not in cols:
        conn.execute("ALTER TABLE clients ADD COLUMN suspended INTEGER NOT NULL DEFAULT 0")
    if "product_id" not in cols:
        conn.execute("ALTER TABLE clients ADD COLUMN product_id INTEGER REFERENCES products(id)")
    if not conn.execute("SELECT 1 FROM products").fetchone():  # birinchi mahsulot
        conn.execute("INSERT INTO products (name, app_id, created_at) VALUES ('EproPos', 'epropos', ?)", (now(),))
    first = conn.execute("SELECT MIN(id) FROM products").fetchone()[0]
    conn.execute("UPDATE clients SET product_id = ? WHERE product_id IS NULL", (first,))
    conn.commit()
    return conn


class Publisher:
    """To'xtatilgan mijozlar ro'yxatini imzolab e'lon qiladi (o'zgarganda darhol, keyin har 20 daqiqada).
    Mijozlarning dasturi internetga ulanganda shu ro'yxatni tekshiradi."""

    def __init__(self, conn, secret):
        self.conn, self.secret = conn, secret
        self.wake = threading.Event()
        self.last_ok = None
        self.error = None

    def start(self):
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                self.publish()
            except Exception as e:
                self.error = str(e)
            self.wake.wait(1200)
            self.wake.clear()

    def publish(self):
        with lock:
            ids = [r[0] for r in self.conn.execute(
                "SELECT shop_id FROM clients WHERE suspended = 1 AND archived = 0 AND shop_id IS NOT NULL")]
        text = obuna.make_status(self.secret, ids, time.time() * 1000)
        topic = obuna.status_topic(obuna.public_key(self.secret))
        req = urllib.request.Request(f"{RELAY}/{topic}", data=text.encode(), method="POST", headers={"Title": "Obuna"})
        try:
            with _web.open(req, timeout=20) as res:
                res.read()
            self.last_ok, self.error = now(), None
        except OSError as e:
            self.error = f"E'lon qilib bo'lmadi (internet bormi?): {e}"


def settings(conn):
    s = {"vendor_name": "", "vendor_phone": ""}
    s.update({r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")})
    return s


CLIENT_SQL = """SELECT c.*, p.name AS product, p.app_id AS app_id,
                (SELECT note FROM payments x WHERE x.client_id = c.id ORDER BY x.id DESC LIMIT 1) AS last_note
                FROM clients c LEFT JOIN products p ON p.id = c.product_id"""


def client_view(row):
    c = dict(row)
    c["demo"] = str(c.pop("last_note", None) or "").startswith("Demo")
    c["days_left"] = (date.fromisoformat(c["paid_until"]) - today()).days if c["paid_until"] else None
    if c.get("suspended"):
        c["status"] = "suspended"
    elif c["paid_until"]:
        left = c["days_left"]
        c["status"] = "active" if left > WARN_DAYS else "warning" if left >= 0 else "expired"
    else:
        c["status"] = "new"
    return c


def text(data, key, limit=200, required=False):
    value = str(data.get(key) or "").strip()[:limit]
    if required and not value:
        raise ApiError(400, "To'ldiring: " + key)
    return value


def client_values(conn, data):
    shop = data.get("shop_id")
    shop_id = obuna.normalize_shop_id(shop) if shop else None
    if shop and not shop_id:
        raise ApiError(400, "Mijoz ID noto'g'ri. Dasturning Obuna sahifasidagi 12 belgili ID (1A2B-3C4D-5E6F)")
    try:
        tariff = max(0, int(float(data.get("tariff") or 0)))
        product_id = int(data.get("product_id") or 0)
    except ValueError:
        raise ApiError(400, "Oylik narx noto'g'ri")
    if not conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone():
        raise ApiError(400, "Dasturni tanlang")
    return {"business": text(data, "business", 120, True), "owner": text(data, "owner", 120),
            "phone": text(data, "phone", 40), "address": text(data, "address", 200), "shop_id": shop_id,
            "tariff": tariff, "note": text(data, "note", 1000), "product_id": product_id}


def get_client(conn, cid):
    row = conn.execute(CLIENT_SQL + " WHERE c.id = ?", (cid,)).fetchone()
    if not row:
        raise ApiError(404, "Mijoz topilmadi")
    return row


def issue_code(conn, secret, client, until, resume=False):
    if not client["shop_id"]:
        raise ApiError(400, "Avval mijoz ID sini kiriting (mijozning dasturida: Sozlamalar -> Obuna)")
    s = settings(conn)
    return obuna.make_code(secret, client["shop_id"], until, s["vendor_name"], s["vendor_phone"], client["business"],
                           resume=resume, app=client["app_id"] or "")


def save_payment(conn, client, amount, months, until, code, note):
    conn.execute("UPDATE clients SET paid_until = ? WHERE id = ?", (until, client["id"]))
    conn.execute("INSERT INTO payments (client_id, amount, months, paid_at, until, code, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (client["id"], amount, months, now(), until, code, note))


# --- API

def api(conn, secret, method, path, data):
    if method == "GET" and path == "/api/state":
        rows = [client_view(r) for r in conn.execute(CLIENT_SQL + " WHERE c.archived = 0")]
        month = today().strftime("%Y-%m")
        paid = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE substr(paid_at, 1, 7) = ?", (month,)).fetchone()[0]
        products = [dict(r) for r in conn.execute("SELECT * FROM products ORDER BY id")]
        live = ("active", "warning")
        for p in products:
            mine = [c for c in rows if c["product_id"] == p["id"]]
            p["clients"] = len(mine)
            p["active"] = sum(1 for c in mine if c["status"] in live)
            p["monthly"] = sum(c["tariff"] for c in mine if c["status"] in live)
        return {"settings": settings(conn), "public_key": obuna.key_text(obuna.public_key(secret)),
                "data_dir": DATA_DIR, "today": today().isoformat(), "products": products,
                "publish": {"last_ok": publisher.last_ok, "error": publisher.error} if publisher else None,
                "stats": {"total": len(rows),
                          "active": sum(1 for c in rows if c["status"] in live),
                          "warning": sum(1 for c in rows if c["status"] == "warning"),
                          "expired": sum(1 for c in rows if c["status"] == "expired"),
                          "suspended": sum(1 for c in rows if c["status"] == "suspended"),
                          "monthly": sum(c["tariff"] for c in rows if c["status"] in live),
                          "paid_this_month": paid}}

    if method == "GET" and path == "/api/clients":
        rows = [client_view(r) for r in conn.execute(CLIENT_SQL + " WHERE c.archived = 0 ORDER BY c.business")]
        order = {"expired": 0, "suspended": 1, "warning": 2, "new": 3, "active": 4}
        rows.sort(key=lambda c: (order[c["status"]], c["days_left"] if c["days_left"] is not None else 0))
        return rows

    if method == "POST" and path == "/api/products":
        name = text(data, "name", 60, True)
        app_id = text(data, "app_id", 40, True).lower()
        if not re.match(r"^[a-z0-9][a-z0-9_-]*$", app_id):
            raise ApiError(400, "Dastur kodi faqat lotin harflari, raqam, - va _ dan iborat bo'lsin (masalan: epropos)")
        if conn.execute("SELECT 1 FROM products WHERE app_id = ?", (app_id,)).fetchone():
            raise ApiError(400, "Bu kod bilan dastur bor")
        conn.execute("INSERT INTO products (name, app_id, note, created_at) VALUES (?, ?, ?, ?)",
                     (name, app_id, text(data, "note", 300), now()))
        return {"ok": True}

    m = re.match(r"^/api/products/(\d+)$", path)
    if m and method == "PUT":
        conn.execute("UPDATE products SET name = ?, note = ? WHERE id = ?",
                     (text(data, "name", 60, True), text(data, "note", 300), int(m.group(1))))
        return {"ok": True}

    if method == "POST" and path == "/api/clients":
        v = client_values(conn, data)
        demo = str(data.get("demo_until") or "")
        if demo:  # yangi mijozga demo (sinov) muddati - sotuvchi o'zi belgilaydi
            try:
                if date.fromisoformat(demo) < today():
                    raise ValueError
            except ValueError:
                raise ApiError(400, "Demo muddati sanasi noto'g'ri")
            if not v["shop_id"]:
                raise ApiError(400, "Demo kod uchun mijoz ID kerak (mijozning dasturida: Sozlamalar -> Obuna)")
        cur = conn.execute("""INSERT INTO clients (business, owner, phone, address, shop_id, tariff, note, product_id, created_at)
                              VALUES (:business, :owner, :phone, :address, :shop_id, :tariff, :note, :product_id, :created)""",
                           dict(v, created=now()))
        client = get_client(conn, cur.lastrowid)
        if not demo:
            return client_view(client)
        code = issue_code(conn, secret, client, demo)
        save_payment(conn, client, 0, 0, demo, code, "Demo (sinov)")
        return dict(client_view(get_client(conn, client["id"])), code=code)

    m = re.match(r"^/api/clients/(\d+)(/pay|/code|/suspend)?$", path)
    if m:
        client = get_client(conn, int(m.group(1)))
        action = m.group(2)
        if method == "GET" and not action:
            res = client_view(client)
            res["payments"] = [dict(r) for r in conn.execute(
                "SELECT * FROM payments WHERE client_id = ? ORDER BY id DESC", (client["id"],))]
            return res
        if method == "PUT" and not action:
            v = client_values(conn, data)
            conn.execute("""UPDATE clients SET business = :business, owner = :owner, phone = :phone, address = :address,
                            shop_id = :shop_id, tariff = :tariff, note = :note, product_id = :product_id WHERE id = :id""",
                         dict(v, id=client["id"]))
            return client_view(get_client(conn, client["id"]))
        if method == "DELETE" and not action:
            conn.execute("UPDATE clients SET archived = 1 WHERE id = ?", (client["id"],))
            return {"ok": True}
        if method == "POST" and action == "/pay":
            # to'lov: muddat oxirgi to'langan kundan (yoki bugundan, agar o'tib ketgan bo'lsa) uzaytiriladi
            try:
                months = int(data.get("months") or 1)
                amount = int(float(data.get("amount") or 0))
            except ValueError:
                raise ApiError(400, "Summa yoki oylar soni noto'g'ri")
            if not 1 <= months <= 60:
                raise ApiError(400, "Oylar soni 1 dan 60 gacha")
            base = today()
            if client["paid_until"] and date.fromisoformat(client["paid_until"]) > base:
                base = date.fromisoformat(client["paid_until"])
            until = add_months(base, months).isoformat()
            code = issue_code(conn, secret, client, until)
            save_payment(conn, client, amount, months, until, code, text(data, "note", 300))
            return {"code": code, "until": until, "client": client_view(get_client(conn, client["id"]))}
        if method == "POST" and action == "/suspend":
            on = bool(data.get("suspended"))
            conn.execute("UPDATE clients SET suspended = ? WHERE id = ?", (1 if on else 0, client["id"]))
            if publisher:
                publisher.wake.set()
            res = {"client": client_view(get_client(conn, client["id"]))}
            if not on and client["shop_id"] and client["paid_until"] and date.fromisoformat(client["paid_until"]) >= today():
                # internetsiz mijoz uchun: qo'lda kiritiladigan "davom ettirish" kodi
                res["code"] = issue_code(conn, secret, client, client["paid_until"], resume=True)
                res["until"] = client["paid_until"]
            return res
        if method == "POST" and action == "/code":
            # to'lovsiz kod: sinov, bepul muddat yoki kodni qayta yuborish
            until = str(data.get("until") or "")
            try:
                date.fromisoformat(until)
            except ValueError:
                raise ApiError(400, "Sana noto'g'ri")
            code = issue_code(conn, secret, client, until)
            if data.get("save"):
                save_payment(conn, client, 0, 0, until, code, text(data, "note", 300) or "To'lovsiz kod")
            return {"code": code, "until": until, "client": client_view(get_client(conn, client["id"]))}

    if method == "PUT" and path == "/api/settings":
        for key in ("vendor_name", "vendor_phone"):
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (key, text(data, key, 100)))
        return settings(conn)

    raise ApiError(404, "Topilmadi")


def backup_zip(conn):
    buf = io.BytesIO()
    copy = sqlite3.connect(":memory:")
    conn.backup(copy)
    dump = "\n".join(copy.iterdump())
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("admin.sql", dump)
        z.write(KEY_PATH, "vendor.key")
        z.writestr("OQING.txt", "Obuna Admin zaxira nusxasi.\nvendor.key - MAXFIY kalit, hech kimga bermang.\n"
                                "Tiklash: vendor.key ni ma'lumotlar papkasiga qo'ying, admin.sql ni sqlite3 bilan admin.db ga yuklang.\n")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "ObunaAdmin/1.0"

    def log_message(self, fmt, *args):
        pass

    def send(self, status, body, ctype="application/json; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def static(self, path):
        if path == "/":
            path = "/index.html"
        full = os.path.realpath(os.path.join(STATIC, path.lstrip("/")))
        if full.startswith(os.path.realpath(STATIC) + os.sep) and os.path.isfile(full):
            with open(full, "rb") as f:
                ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                return self.send(200, f.read(), ctype)
        self.send(404, b"{}")

    def handle_any(self, method):
        path = urlparse(self.path).path
        # faqat shu kompyuterdan (boshqa sayt brauzer orqali so'rov yubora olmasin)
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return self.send(403, b'{"error": "Faqat shu kompyuterdan"}')
        if not path.startswith("/api/"):
            return self.static(path) if method == "GET" else self.send(404, b"{}")
        conn, secret = self.server.conn, self.server.secret
        try:
            if path == "/api/backup":
                with lock:
                    body = backup_zip(conn)
                name = f"obuna-admin-{today().isoformat()}.zip"
                return self.send(200, body, "application/zip", {"Content-Disposition": f'attachment; filename="{name}"'})
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}") if length else {}
            with lock:
                try:
                    res = api(conn, secret, method, path, data)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
            self.send(200, json.dumps(res, ensure_ascii=False).encode())
        except ApiError as e:
            self.send(e.status, json.dumps({"error": e.message}, ensure_ascii=False).encode())
        except (ValueError, TypeError) as e:
            self.send(400, json.dumps({"error": f"Noto'g'ri ma'lumot: {e}"}, ensure_ascii=False).encode())

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")

    def do_PUT(self):
        self.handle_any("PUT")

    def do_DELETE(self):
        self.handle_any("DELETE")


publisher = None


def make_server(port=PORT):
    global publisher
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.conn = connect()
    server.secret = load_secret()
    publisher = Publisher(server.conn, server.secret)
    publisher.start()
    return server


def main():
    url = f"http://127.0.0.1:{PORT}"
    try:
        server = make_server()
    except OSError:  # allaqachon ochiq
        webbrowser.open(url)
        return
    print(f"Obuna Admin: {url}\nMa'lumotlar: {DATA_DIR}")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
