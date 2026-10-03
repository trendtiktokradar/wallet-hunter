"""Cliente HTTP con límite de peticiones por fuente, reintentos con backoff y contador de créditos.
Solo stdlib. Nunca escribe URLs con api-key en los logs (se redactan)."""
import json, threading, time, urllib.request, urllib.error, urllib.parse, os, logging
from .config import redact, STATE_DIR

log = logging.getLogger("wh")
UA = "Mozilla/5.0 (X11; Linux x86_64) WalletHunter/0.1"


class RateLimiter:
    def __init__(self, per_second):
        self.min_interval = 1.0 / per_second if per_second > 0 else 0
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            if now < self.next_t:
                time.sleep(self.next_t - now)
                now = time.monotonic()
            self.next_t = now + self.min_interval


class SourceStatus:
    """Estado de cada fuente (para el indicador de arriba a la derecha del panel) + uso de créditos."""
    def __init__(self):
        self.lock = threading.Lock()
        self.path = os.path.join(STATE_DIR, "sources.json")
        try:
            self.data = json.load(open(self.path))
        except Exception:
            self.data = {}

    def mark(self, name, ok, err=None, credits=0, calls=1):
        with self.lock:
            d = self.data.setdefault(name, {})
            d["ok"] = bool(ok)
            d["last"] = int(time.time())
            if ok:
                d["last_ok"] = d["last"]
                d.pop("error", None)
            else:
                d["error"] = redact(str(err))[:200] if err else "error"
            month = time.strftime("%Y-%m")
            if d.get("month") != month:
                d["month"], d["credits_month"], d["calls_month"] = month, 0, 0
            day = time.strftime("%Y-%m-%d")
            if d.get("day") != day:
                d["day"], d["calls_day"] = day, 0
            d["credits_month"] = d.get("credits_month", 0) + credits
            d["calls_month"] = d.get("calls_month", 0) + calls
            d["calls_day"] = d.get("calls_day", 0) + calls

    def set(self, name, **kw):
        with self.lock:
            self.data.setdefault(name, {}).update(kw)

    def save(self):
        with self.lock:
            os.makedirs(STATE_DIR, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self.path)


STATUS = SourceStatus()


class HttpError(Exception):
    def __init__(self, code, body):
        super().__init__(f"HTTP {code}: {body[:200]}")
        self.code, self.body = code, body


def request(url, *, method="GET", body=None, headers=None, limiter=None, source=None, credits=0,
            retries=5, timeout=40, expect_json=True):
    hdr = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        hdr.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode() if not isinstance(body, (bytes, str)) else (body.encode() if isinstance(body, str) else body)
        hdr.setdefault("Content-Type", "application/json")
    delay = 1.5
    last = None
    for attempt in range(retries):
        if limiter:
            limiter.wait()
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=hdr)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
            if source:
                STATUS.mark(source, True, credits=credits)
            return json.loads(raw) if expect_json else raw
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
            last = HttpError(e.code, redact(txt))
            if e.code in (429, 500, 502, 503, 504, 520, 522, 524):
                ra = e.headers.get("Retry-After") if e.headers else None
                wait = max(float(ra), delay) if ra and ra.replace(".", "").isdigit() else delay
                log.debug("HTTP %s en %s, reintento en %.1fs", e.code, source, wait)
                time.sleep(min(wait, 60))
                delay = min(delay * 2, 60)
                continue
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            last = e
            time.sleep(delay)
            delay = min(delay * 2, 60)
    if source:
        STATUS.mark(source, False, err=last, credits=0)
    raise last if isinstance(last, Exception) else RuntimeError(redact(str(last)))
