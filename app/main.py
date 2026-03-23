from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from string import Formatter
from typing import Any
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request


app = FastAPI(title="手机配件价格查询")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
ALLOWED_QUERY_TEMPLATE_FIELDS = {"model", "accessory"}


@dataclass
class Vendor:
    id: int
    name: str
    base_url: str
    username: str
    password: str
    query_template: str = "/search?model={model}&accessory={accessory}"
    price_selector: str | None = None
    timeout_sec: int = 10
    extra: dict[str, Any] = field(default_factory=dict)


class VendorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    base_url: str = Field(..., min_length=1)
    username: str = ""
    password: str = ""
    query_template: str = "/search?model={model}&accessory={accessory}"
    price_selector: str | None = None
    timeout_sec: int = Field(default=10, ge=3, le=60)


class QueryRequest(BaseModel):
    phone_model: str = Field(..., min_length=1, max_length=80)
    accessory_name: str = Field(..., min_length=1, max_length=80)


vendors: list[Vendor] = []
next_vendor_id = 1


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/vendors")
def list_vendors():
    return [
        {
            "id": v.id,
            "name": v.name,
            "base_url": v.base_url,
            "username": v.username,
            "password_masked": "*" * len(v.password),
            "query_template": v.query_template,
            "price_selector": v.price_selector,
            "timeout_sec": v.timeout_sec,
        }
        for v in vendors
    ]


def _validate_query_template(query_template: str) -> None:
    formatter = Formatter()
    try:
        for _, field_name, _, _ in formatter.parse(query_template):
            if field_name is None:
                continue
            base_field = field_name.split(".", 1)[0].split("[", 1)[0]
            if base_field not in ALLOWED_QUERY_TEMPLATE_FIELDS:
                allowed_fields = ", ".join(sorted(ALLOWED_QUERY_TEMPLATE_FIELDS))
                raise ValueError(f"仅支持以下占位符: {allowed_fields}")
    except ValueError as exc:
        raise ValueError(f"query_template 无效: {exc}") from exc


@app.post("/api/vendors")
def add_vendor(payload: VendorCreate):
    global next_vendor_id
    try:
        _validate_query_template(payload.query_template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    vendor = Vendor(id=next_vendor_id, **payload.model_dump())
    vendors.append(vendor)
    next_vendor_id += 1
    return {"message": "配件网站添加成功", "vendor_id": vendor.id}


def _mock_price(vendor_name: str, phone_model: str, accessory_name: str) -> float:
    source = f"{vendor_name}:{phone_model}:{accessory_name}".encode("utf-8")
    digest = hashlib.sha256(source).hexdigest()
    cents = int(digest[:8], 16) % 7000 + 1999
    return round(cents / 100, 2)


def _first_number(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d{1,2})?)", text.replace(",", ""))
    return float(match.group(1)) if match else None


def _build_query_path(vendor: Vendor, phone_model: str, accessory_name: str) -> str:
    _validate_query_template(vendor.query_template)
    try:
        return vendor.query_template.format(
            model=quote_plus(phone_model),
            accessory=quote_plus(accessory_name),
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(f"query_template 无效: {exc}") from exc


def _coerce_price(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _extract_json_price(data: Any) -> tuple[float | None, str | None]:
    if not isinstance(data, dict):
        return None, "JSON 未找到可用价格字段"

    invalid_fields: list[str] = []
    for key in ("price", "lowest_price", "min_price"):
        if key not in data:
            continue
        price = _coerce_price(data[key])
        if price is not None:
            return price, None
        invalid_fields.append(key)

    if invalid_fields:
        return None, f"JSON 价格字段格式无效: {', '.join(invalid_fields)}"
    return None, "JSON 未找到可用价格字段"


async def fetch_price(vendor: Vendor, phone_model: str, accessory_name: str) -> dict[str, Any]:
    if vendor.base_url.startswith("mock://"):
        return {
            "vendor": vendor.name,
            "price": _mock_price(vendor.name, phone_model, accessory_name),
            "source": "mock",
            "status": "ok",
        }

    try:
        path = _build_query_path(vendor, phone_model, accessory_name)
    except ValueError as exc:
        return {
            "vendor": vendor.name,
            "price": None,
            "status": "error",
            "error": str(exc),
        }

    query_url = f"{vendor.base_url.rstrip('/')}{path}"

    auth = None
    if vendor.username and vendor.password:
        auth = (vendor.username, vendor.password)

    try:
        async with httpx.AsyncClient(timeout=vendor.timeout_sec) as client:
            response = await client.get(query_url, auth=auth)
            response.raise_for_status()
    except Exception as exc:
        return {
            "vendor": vendor.name,
            "price": None,
            "status": "error",
            "error": f"请求失败: {exc}",
            "query_url": query_url,
        }

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        price, error = _extract_json_price(response.json())
        return {
            "vendor": vendor.name,
            "price": price,
            "status": "ok" if price is not None else "error",
            "error": error,
            "query_url": query_url,
        }

    if vendor.price_selector:
        soup = BeautifulSoup(response.text, "html.parser")
        node = soup.select_one(vendor.price_selector)
        if node:
            price = _first_number(node.get_text(" ", strip=True))
            if price is not None:
                return {
                    "vendor": vendor.name,
                    "price": price,
                    "status": "ok",
                    "query_url": query_url,
                }

    fallback_price = _first_number(response.text)
    return {
        "vendor": vendor.name,
        "price": fallback_price,
        "status": "ok" if fallback_price is not None else "error",
        "error": None if fallback_price is not None else "未在页面中解析到价格",
        "query_url": query_url,
    }


@app.post("/api/query")
async def query_prices(payload: QueryRequest):
    if not vendors:
        raise HTTPException(status_code=400, detail="请先在后台添加至少一个配件网站")

    results = []
    for vendor in vendors:
        result = await fetch_price(vendor, payload.phone_model, payload.accessory_name)
        results.append(result)

    valid_prices = [r["price"] for r in results if r.get("price") is not None]
    best_price = min(valid_prices) if valid_prices else None

    return {
        "phone_model": payload.phone_model,
        "accessory_name": payload.accessory_name,
        "best_price": best_price,
        "results": results,
    }


@app.post("/api/seed-demo")
def seed_demo_data():
    global next_vendor_id
    if vendors:
        return {"message": "已有网站配置，跳过演示数据注入", "count": len(vendors)}

    demo_vendors = [
        Vendor(id=next_vendor_id, name="配件站 A", base_url="mock://site-a", username="demo", password="demo"),
        Vendor(id=next_vendor_id + 1, name="配件站 B", base_url="mock://site-b", username="demo", password="demo"),
        Vendor(id=next_vendor_id + 2, name="配件站 C", base_url="mock://site-c", username="demo", password="demo"),
    ]
    vendors.extend(demo_vendors)
    next_vendor_id += len(demo_vendors)
    return {"message": "已创建演示网站", "count": len(vendors)}
