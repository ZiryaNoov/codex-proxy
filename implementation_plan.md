# codex-proxy — الرؤية الشاملة

المشروع في حالة ممتازة كـ v1.0 — يعمل، يحل مشكلة حقيقية، والكود نظيف. لكن فيه طبقات من التحسينات تتراوح بين "لازم الحين" و "رؤية مستقبلية".

---

## 🔴 أولوية عالية — لازم تنصلح

### 1. لا يوجد Git Repository

المشروع بالكامل بدون version control. أي خطأ، أي تجربة فاشلة = لا رجعة.

```bash
git init
# + .gitignore لـ Python
# + initial commit
```

---

### 2. Usage Tracking = 0 دائماً في Streaming

#### المشكلة
في [translator.py:305-306](file:///f:/Projects/codex-proxy/src/codex_proxy/translator.py#L305-L306) و [server.py:274-276](file:///f:/Projects/codex-proxy/src/codex_proxy/server.py#L274-L276):
```python
"usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
```
الـ tokens دائماً صفر. Codex CLI يعتمد على هذي الأرقام لعرض الاستهلاك.

#### الحل
معظم الـ backends تدعم `stream_options`:
```diff
 cc_body["stream"] = True
+cc_body["stream_options"] = {"include_usage": True}
```
بعدها آخر chunk في الـ stream يحتوي `usage` — نلتقطه ونمرّره.

> [!IMPORTANT]
> بعض backends (Ollama مثلاً) ما تدعم `stream_options`. يحتاج fallback يحسب تقريبي أو يتجاهل بصمت.

---

### 3. WebSocket: خطأ upstream = رد "ناجح" للعميل

#### المشكلة
في [server.py:221-223](file:///f:/Projects/codex-proxy/src/codex_proxy/server.py#L221-L223):
```python
except Exception as e:
    logger.error("WS upstream error: %s", e)
```
بعد الـ except، الكود يكمل ويرسل `response.completed` بالنص الجزئي كأن كل شيء تمام.

#### الحل
```python
except Exception as e:
    logger.error("WS upstream error: %s", e)
    await ws.send_text(json.dumps({
        "type": "error",
        "error": {"message": str(e), "code": "upstream_error"}
    }))
    continue  # تخطي باقي الـ completion events
```

---

### 4. لا README.md

المشروع جاهز لـ GitHub لكن بدون README. المستخدم الجديد ما يعرف:
- وش هو codex-proxy؟
- كيف يثبّته؟
- كيف يضبط الـ config؟
- كيف يربطه بـ Codex CLI؟

#### المقترح
README شامل يغطي:
- شرح سريع + رسم بياني للمعمارية
- التثبيت (pip install + manual)
- الإعداد (config.toml + env vars)
- الاستخدام مع Codex CLI
- قائمة المزوّدين المدعومين مع أمثلة
- الـ API endpoints
- الـ auto-start setup

---

## 🟡 أولوية متوسطة — تحسينات نوعية

### 5. تكرار منطق الـ Streaming (أكبر دين تقني)

#### المشكلة
نفس المنطق مكتوب **مرتين**:

| الموقع | السطور | الوظيفة |
|---|---|---|
| [translator.py:217-257](file:///f:/Projects/codex-proxy/src/codex_proxy/translator.py#L217-L257) | 40 سطر | SSE parsing في `stream_cc_to_response` |
| [server.py:180-221](file:///f:/Projects/codex-proxy/src/codex_proxy/server.py#L180-L221) | 41 سطر | نفس SSE parsing في WebSocket handler |

وكذلك بناء الـ `final_out`:

| الموقع | السطور |
|---|---|
| [translator.py:275-300](file:///f:/Projects/codex-proxy/src/codex_proxy/translator.py#L275-L300) | 25 سطر |
| [server.py:242-270](file:///f:/Projects/codex-proxy/src/codex_proxy/server.py#L242-L270) | 28 سطر |

#### الحل — Refactor إلى core iterator
```python
# translator.py
async def parse_cc_stream(line_iter):
    """Core parser — yields (event_type, data) tuples."""
    async for line in line_iter:
        if not line.startswith("data: "): continue
        payload = line[6:].strip()
        if payload == "[DONE]": break
        chunk = json.loads(payload)
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            if delta.get("reasoning_content"):
                yield ("reasoning", delta["reasoning_content"])
            if delta.get("content"):
                yield ("text", delta["content"])
            for tc in delta.get("tool_calls", []):
                yield ("tool_call", tc)
        if chunk.get("usage"):
            yield ("usage", chunk["usage"])

def build_final_output(mid, full_text, reasoning_text, tool_calls):
    """Build the final output list — used by both HTTP and WS."""
    ...
```
بعدها كل من HTTP streaming و WebSocket يستخدمون نفس الـ parser.

---

### 6. Global Mutable State → App State

#### المشكلة
```python
_config: ProxyConfig | None = None
_store = ResponseStore()
_client: httpx.AsyncClient | None = None
_start_time = 0.0
_request_count = 0
```
Module-level globals = صعوبة في الاختبار + لا يمكن تشغيل أكثر من instance.

#### الحل
```python
@dataclass
class AppState:
    config: ProxyConfig
    store: ResponseStore
    client: httpx.AsyncClient
    start_time: float
    request_count: int = 0

# في startup
app.state.proxy = AppState(config=config, ...)

# في endpoint
state: AppState = request.app.state.proxy
```

---

### 7. `log_dir` — Dead Code

[config.py:45](file:///f:/Projects/codex-proxy/src/codex_proxy/config.py#L45):
```python
log_dir: Path = field(default_factory=lambda: DEFAULT_DIR / "logs")
```
هذا الحقل موجود في الـ config لكن **ما أحد يستخدمه**. إما:
- **نفعّله**: نكتب request/response logs إلى `log_dir` (مفيد للتصحيح)
- **نحذفه**: نظافة كود

#### اقتراحي — نفعّله كـ debug logging
```python
# middleware يسجّل الطلبات
@app.middleware("http")
async def log_requests(request, call_next):
    if state.config.server.log_level == "debug":
        # log request body + response to log_dir
        ...
```

---

### 8. `_rid()` — Private Function مستوردة Cross-Module

[server.py:20](file:///f:/Projects/codex-proxy/src/codex_proxy/server.py#L20):
```python
from .translator import (..., _rid)
```
دالة بـ `_` prefix مستوردة خارج الملف. إما:
- أعد تسميتها `generate_response_id()`
- أو اعتبرها internal API وارفع الـ prefix

---

### 9. Tests — الأساس المفقود

لا يوجد أي test. المقترح:

```
tests/
  test_translator.py    # Unit: input_to_messages, convert_tools, cc_to_response
  test_store.py          # Unit: put/get/resolve_input/TTL expiry
  test_config.py         # Unit: load_config defaults, env var fallback
  test_server.py         # Integration: httpx.AsyncClient + TestClient
```

**الأولوية**: `test_translator.py` — هو قلب المشروع وأسهل ملف يُختبر (pure functions).

---

### 10. .gitignore

```gitignore
__pycache__/
*.pyc
*.egg-info/
dist/
build/
.venv/
.env
```

---

## 🟢 تحسينات مستقبلية — رؤية طويلة المدى

### 11. Retry Logic للـ Upstream

طلب واحد فاشل ≠ المزوّد معطّل. Retry بسيط:
```python
# 1 retry مع backoff قصير
for attempt in range(2):
    try:
        resp = await _client.post(...)
        if resp.status_code < 500:
            break
    except httpx.TransportError:
        if attempt == 0:
            await asyncio.sleep(0.5)
```

---

### 12. GET /responses/{id} — استرجاع Response سابق

Codex CLI ممكن يحتاج يسترجع response سابق بدون `previous_response_id`:
```python
@app.get("/responses/{response_id}")
async def get_response(response_id: str):
    resp = _store.get(response_id)
    if not resp:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(resp)
```

---

### 13. Graceful Shutdown

```python
@app.on_event("shutdown")
async def shutdown():
    if _client:
        await _client.aclose()
    logger.info("codex-proxy shutting down")
```
يضمن إغلاق الـ httpx connection pool نظيف.

---

### 14. Health Check مع Upstream Ping

الـ `/health` الحالي يقول "ok" حتى لو الـ backend ميت:
```python
@app.get("/health")
async def health():
    # Optional: ping backend
    try:
        r = await _client.get(f"{_backend_url()}/models", timeout=5)
        backend_ok = r.status_code < 400
    except:
        backend_ok = False
    return {"status": "ok", "backend": "ok" if backend_ok else "unreachable", ...}
```

---

### 15. Config Hot-Reload

بدل ما تعيد تشغيل البروكسي كل ما تغيّر الـ config:
```python
# SIGHUP handler أو endpoint
@app.post("/reload")
async def reload_config():
    global _config
    _config = load_config()
    return {"status": "reloaded"}
```

---

### 16. Provider-Specific Quirks

كل مزوّد عنده خصوصيات:

| المزوّد | الخصوصية |
|---|---|
| Ollama | ما يحتاج API key حقيقي + `stream_options` غير مدعوم |
| Groq | Rate limits صارمة + headers مختلفة |
| OpenRouter | يحتاج `HTTP-Referer` header |
| Together | `stop` parameter format مختلف |

ممكن يكون هناك `providers/` directory بملف لكل مزوّد:
```python
class ProviderAdapter:
    def adjust_request(self, cc_body: dict) -> dict: ...
    def adjust_headers(self, headers: dict) -> dict: ...
```

---

### 17. Docker Support

```dockerfile
FROM python:3.12-slim
COPY . /app
RUN pip install /app
EXPOSE 4242
CMD ["codex-proxy"]
```

---

### 18. TTL Store → يكون Configurable

[store.py:13](file:///f:/Projects/codex-proxy/src/codex_proxy/store.py#L13) — الـ 10 دقائق hardcoded:
```python
TTL_SECONDS = 600
MAX_ENTRIES = 100
```
الأفضل يكون قابل للضبط من الـ config:
```toml
[store]
ttl_seconds = 1800     # 30 دقيقة
max_entries = 200
```

---

## 📋 ترتيب التنفيذ المقترح

| المرحلة | المهام | الجهد |
|---|---|---|
| **الآن** | Git init + .gitignore + initial commit | 5 دقائق |
| **الآن** | README.md شامل | 20 دقيقة |
| **قريب** | إصلاح Usage tracking في streaming | 15 دقيقة |
| **قريب** | إصلاح WS error propagation | 10 دقائق |
| **قريب** | Graceful shutdown | 5 دقائق |
| **قريب** | `_rid` → `generate_response_id` | 2 دقيقة |
| **متوسط** | Refactor streaming duplication | 45 دقيقة |
| **متوسط** | Tests (translator + store) | 30 دقيقة |
| **متوسط** | تفعيل log_dir | 15 دقيقة |
| **لاحقاً** | App State refactor | 30 دقيقة |
| **لاحقاً** | GET /responses/{id} | 10 دقائق |
| **لاحقاً** | Retry logic | 15 دقيقة |
| **لاحقاً** | Provider adapters | 1-2 ساعة |
| **لاحقاً** | Docker | 10 دقائق |
| **لاحقاً** | Config hot-reload | 20 دقيقة |
| **لاحقاً** | Configurable TTL/max | 10 دقائق |

## Open Questions

> [!IMPORTANT]
> 1. **أي مرحلة تبي نبدأ فيها؟** الكل مرتّب حسب الأولوية لكن ممكن تختار حسب حاجتك.
> 2. **هل تبي README بالعربي أو بالإنجليزي أو الاثنين؟**
> 3. **هل فيه مزوّدين محددين تستخدمهم وتبيني أضبط الـ provider quirks لهم؟**
> 4. **هل تبي الـ tests بـ pytest ولا unittest؟**
