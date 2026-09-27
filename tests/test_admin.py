"""Obuna Admin: dasturlar, mijoz, demo, to'lov, kod, vaqtincha to'xtatish, zaxira."""

import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP = tempfile.TemporaryDirectory()
os.environ["OBUNA_DATA"] = TMP.name
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
import admin  # noqa: E402
import obuna  # noqa: E402


class FakeRelay(BaseHTTPRequestHandler):
    """ntfy.sh o'rniga: e'lon qilingan xabarlarni eslab qoladi."""
    topics = {}

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        self.topics.setdefault(self.path.strip("/"), []).append(body)
        self.send_response(200)
        self.end_headers()


class AdminTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.relay = ThreadingHTTPServer(("127.0.0.1", 0), FakeRelay)
        threading.Thread(target=cls.relay.serve_forever, daemon=True).start()
        admin.RELAY = f"http://127.0.0.1:{cls.relay.server_address[1]}"
        cls.server = admin.make_server(0)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.relay.shutdown()

    def setUp(self):
        os.environ["OBUNA_TODAY"] = "2027-01-10"

    def tearDown(self):
        del os.environ["OBUNA_TODAY"]

    def call(self, method, path, body=None, host=None):
        req = urllib.request.Request(self.url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **({"Host": host} if host else {})})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req) as res:
                raw = res.read()
                return res.status, (json.loads(raw) if res.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_flow(self):
        _, st = self.call("GET", "/api/state")
        epropos = st["products"][0]
        self.assertEqual((epropos["name"], epropos["app_id"]), ("EproPos", "epropos"))
        # yangi startap
        self.assertEqual(self.call("POST", "/api/products", {"name": "Cafe", "app_id": "Kafe pos!"})[0], 400)
        self.assertEqual(self.call("POST", "/api/products", {"name": "EproCafe", "app_id": "eprocafe"})[0], 200)
        self.assertEqual(self.call("POST", "/api/products", {"name": "Takror", "app_id": "eprocafe"})[0], 400)
        cafe = next(p for p in self.call("GET", "/api/state")[1]["products"] if p["app_id"] == "eprocafe")

        self.call("PUT", "/api/settings", {"vendor_name": "Doston", "vendor_phone": "+998 90 111 22 33"})
        self.assertEqual(self.call("POST", "/api/clients", {"business": "X", "product_id": epropos["id"], "shop_id": "xyz"})[0], 400)
        status, c = self.call("POST", "/api/clients", {"business": "Baraka market", "owner": "Ali", "tariff": 150000,
                                                       "shop_id": "1a2b3c4d5e6f", "product_id": epropos["id"]})
        self.assertEqual((status, c["shop_id"], c["status"], c["product"]), (200, "1A2B-3C4D-5E6F", "new", "EproPos"))
        status, res = self.call("POST", f"/api/clients/{c['id']}/pay", {"months": 1, "amount": 150000})
        self.assertEqual((status, res["until"]), (200, "2027-02-10"))
        info = obuna.read_code(res["code"])
        self.assertEqual((info["s"], info["u"], info["n"], info["a"]), ("1A2B-3C4D-5E6F", "2027-02-10", "Doston", "epropos"))
        _, res = self.call("POST", f"/api/clients/{c['id']}/pay", {"months": 3, "amount": 450000})
        self.assertEqual(res["until"], "2027-05-10")  # oldindan to'lov - oxirgi sanadan uzaytiriladi

        # boshqa dastur mijozi va demo muddati
        self.assertEqual(self.call("POST", "/api/clients", {"business": "Kafe", "product_id": cafe["id"],
                                                            "demo_until": "2027-01-17"})[0], 400)  # ID siz demo yo'q
        _, d = self.call("POST", "/api/clients", {"business": "Kafe", "product_id": cafe["id"], "shop_id": "BBBB-CCCC-DDDD",
                                                  "demo_until": "2027-01-17"})
        self.assertEqual((d["paid_until"], d["demo"], obuna.read_code(d["code"])["a"]), ("2027-01-17", True, "eprocafe"))
        _, st = self.call("GET", "/api/state")
        by_app = {p["app_id"]: p for p in st["products"]}
        self.assertEqual((by_app["epropos"]["clients"], by_app["eprocafe"]["clients"]), (1, 1))

        # vaqtincha to'xtatish: imzolangan ro'yxat e'lon qilinadi, davom ettirishda kod beriladi
        topic = obuna.status_topic(obuna.public_key(self.server.secret))
        _, res = self.call("POST", f"/api/clients/{c['id']}/suspend", {"suspended": True})
        self.assertEqual(res["client"]["status"], "suspended")
        admin.publisher.publish()
        pub = obuna.public_key(self.server.secret)
        self.assertEqual(obuna.read_status(FakeRelay.topics[topic][-1], pub)["x"], ["1A2B-3C4D-5E6F"])
        _, res = self.call("POST", f"/api/clients/{c['id']}/suspend", {"suspended": False})
        self.assertEqual((res["client"]["status"], obuna.read_code(res["code"]).get("r")), ("active", 1))
        admin.publisher.publish()
        self.assertEqual(obuna.read_status(FakeRelay.topics[topic][-1], pub)["x"], [])

        # boshqa sayt (Host) orqali so'rov rad etiladi; zaxira: kalit va ma'lumotlar
        self.assertEqual(self.call("GET", "/api/state", host="evil.example")[0], 403)
        _, raw = self.call("GET", "/api/backup")
        self.assertIn("vendor.key", zipfile.ZipFile(io.BytesIO(raw)).namelist())

    def test_ed25519_rfc8032(self):
        sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        self.assertEqual(obuna.public_key(sk).hex(), "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        sig = obuna.sign(sk, b"")
        self.assertTrue(obuna.verify(obuna.public_key(sk), b"", sig))
        self.assertFalse(obuna.verify(obuna.public_key(sk), b"x", sig))


if __name__ == "__main__":
    unittest.main()
