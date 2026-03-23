import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class FakeResponse:
    def __init__(self, data, headers=None, text=""):
        self._data = data
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._data

    def raise_for_status(self):
        return None


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, query_url, auth=None):
        return self.response


class QueryPriceTests(unittest.TestCase):
    def setUp(self):
        self._vendors = list(main.vendors)
        self._next_vendor_id = main.next_vendor_id
        main.vendors.clear()
        main.next_vendor_id = 1
        self.client = TestClient(main.app)

    def tearDown(self):
        main.vendors.clear()
        main.vendors.extend(self._vendors)
        main.next_vendor_id = self._next_vendor_id

    def test_add_vendor_rejects_invalid_query_template(self):
        response = self.client.post(
            "/api/vendors",
            json={
                "name": "Broken vendor",
                "base_url": "https://example.com",
                "query_template": "/search?q={phone}",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("query_template 无效", response.json()["detail"])

    def test_query_reports_invalid_query_template_per_vendor(self):
        main.vendors.extend(
            [
                main.Vendor(id=1, name="Broken vendor", base_url="https://broken.example", username="", password="", query_template="/search?q={phone}"),
                main.Vendor(id=2, name="Mock vendor", base_url="mock://site-a", username="", password=""),
            ]
        )

        response = self.client.post(
            "/api/query",
            json={"phone_model": "iPhone 16", "accessory_name": "Case"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["results"][0]["status"], "error")
        self.assertIn("query_template 无效", body["results"][0]["error"])
        self.assertEqual(body["results"][1]["status"], "ok")
        self.assertIsNotNone(body["best_price"])

    def test_query_reports_invalid_json_price_per_vendor(self):
        main.vendors.extend(
            [
                main.Vendor(id=1, name="JSON vendor", base_url="https://json.example", username="", password=""),
                main.Vendor(id=2, name="Mock vendor", base_url="mock://site-a", username="", password=""),
            ]
        )

        fake_response = FakeResponse(
            {"price": "¥99.00"},
            headers={"content-type": "application/json"},
        )
        with patch.object(main.httpx, "AsyncClient", return_value=FakeAsyncClient(fake_response)):
            response = self.client.post(
                "/api/query",
                json={"phone_model": "iPhone 16", "accessory_name": "Case"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["results"][0]["status"], "error")
        self.assertEqual(body["results"][0]["price"], None)
        self.assertIn("JSON 价格字段格式无效", body["results"][0]["error"])
        self.assertEqual(body["results"][1]["status"], "ok")
        self.assertIsNotNone(body["best_price"])


class JsonPriceExtractionTests(unittest.TestCase):
    def test_extract_json_price_flags_non_numeric_strings(self):
        price, error = main._extract_json_price({"price": "¥99.00"})

        self.assertIsNone(price)
        self.assertEqual(error, "JSON 价格字段格式无效: price")

    def test_extract_json_price_accepts_numeric_values(self):
        price, error = main._extract_json_price({"lowest_price": "99.00"})

        self.assertEqual(price, 99.0)
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
