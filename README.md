# 手机配件查询 APP

这是一个简单的原型：

- 后台可录入多个配件网站（地址、用户名、密码、查询路径模板、价格选择器）。
- 前台输入手机型号和配件名后，会并行（当前实现为顺序）查询每个网站并汇总价格。
- 支持演示站点（`mock://`）快速体验。

## 启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

打开 <http://localhost:8000>

## 说明

1. 对真实网站，当前是基础 HTTP 请求逻辑：
   - 可设置 `query_template`，例如：`/search?q={model}+{accessory}`
   - 如果返回 JSON，会尝试读取 `price` / `lowest_price` / `min_price`
   - 如果返回 HTML，可设置 `price_selector`（CSS 选择器）抓价格
2. 若网站需要复杂登录（验证码/JS 渲染），建议改造为官方 API 对接或加入浏览器自动化。
