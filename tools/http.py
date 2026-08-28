import time, httpx
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36", "Accept": "application/json"}

def get_json(url, params=None, headers=None, retries=2, timeout=30):
    """GET with backoff. Returns (data, None) or (None, error_string). Never raises."""
    h = {**UA, **(headers or {})}
    delay = 1.0
    for attempt in range(retries + 1):
        try:
            r = httpx.get(url, params=params, headers=h, timeout=timeout, follow_redirects=True)
            if r.status_code == 200:
                return r.json(), None
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(delay); delay *= 2; continue
            return None, f"HTTP {r.status_code}: {r.text[:140]}"
        except Exception as e:
            if attempt < retries: time.sleep(delay); delay *= 2; continue
            return None, f"{type(e).__name__}: {e}"
    return None, "unreachable"

def post_json(url, json, headers=None, retries=2, timeout=30):
    h = {**UA, **(headers or {})}
    delay = 1.0
    for attempt in range(retries + 1):
        try:
            r = httpx.post(url, json=json, headers=h, timeout=timeout)
            if r.status_code == 200: return r.json(), None
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(delay); delay *= 2; continue
            return None, f"HTTP {r.status_code}: {r.text[:140]}"
        except Exception as e:
            if attempt < retries: time.sleep(delay); delay *= 2; continue
            return None, f"{type(e).__name__}: {e}"
    return None, "unreachable"
