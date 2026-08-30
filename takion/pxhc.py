import re
import time
import urllib.parse
from json import loads
from urllib.parse import urljoin

import requests

from .result import ExampleError
from .transport import parse, validate

API_URL = "https://pxhc.takionapi.tech"

APPID_PATTERN = re.compile(r"_pxAppId\s*=\s*['\"]([A-Za-z0-9]+)['\"]")
UUID_PATTERN = re.compile(r"[?&]uuid=([0-9a-fA-F-]{8,})")
VID_PATTERN = re.compile(r"[?&]vid=([0-9a-fA-F-]{8,})")


def nav_headers(accept_language: str = "en-GB,en-US;q=0.9,en;q=0.8") -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Accept-Language": accept_language,
    }


class PxhcTarget:
    def __init__(
        self,
        name: str,
        trigger_url: str,
        app_id: str,
        accept_language: str = "en-GB,en-US;q=0.9,en;q=0.8",
        timeout: int = 30,
        app_id_in_path: bool = False,
    ) -> None:
        self.name = name
        self.trigger_url = trigger_url
        self.app_id = app_id
        self.accept_language = accept_language
        self.timeout = timeout
        self.app_id_in_path = app_id_in_path

    @property
    def headers(self) -> dict:
        return nav_headers(self.accept_language)

    @property
    def short_url(self) -> str:
        return self.trigger_url.split("?")[0].replace("https://", "")


def proxy_url(proxy: str) -> str:
    value = (proxy or "").strip()
    if "://" in value:
        return value
    parts = value.split(":")
    if len(parts) >= 4:
        host, port, user = parts[0], parts[1], parts[2]
        password = ":".join(parts[3:])
        user = urllib.parse.quote(user, safe="")
        password = urllib.parse.quote(password, safe="")
        return f"http://{user}:{password}@{host}:{port}"
    if len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    return f"http://{value}"


class TLSResponse:
    def __init__(self, resp: dict):
        self.status_code = resp.get("status_code")
        self.text = resp.get("body")
        self.headers = resp.get("headers", {})
        self.raw_json = resp

    def json(self):
        return loads(self.text)


class TakionPxHC:
    def __init__(self, api_key: str, proxy: str, target: PxhcTarget) -> None:
        self.api_key = api_key
        self.proxy = proxy
        self.target = target
        self.proxies = {"http": proxy_url(proxy), "https": proxy_url(proxy)}

    def get(self, url: str, headers: dict = None, **kwargs) -> TLSResponse:
        response = requests.get(
            url,
            headers=headers or self.target.headers,
            proxies=self.proxies,
            timeout=self.target.timeout,
            **kwargs,
        )
        return TLSResponse({
            "status_code": response.status_code,
            "body": response.text,
            "headers": dict(response.headers),
        })

    def hammer_until_blocked(self, max_reqs: int = 60, delay: float = 0.3,
                             budget: float = 150) -> tuple:
        target = self.target
        good = bad = 0
        deadline = time.time() + budget
        for index in range(max_reqs):
            if time.time() > deadline:
                raise ExampleError(
                    f"No block within {budget:.0f}s (ok={good} err={bad} after {index} requests). This exit is too slow or too clean."
                )
            try:
                response = self.get(target.trigger_url, allow_redirects=False)
                good += 1
            except Exception as error:
                bad += 1
                if (bad >= 8 and good == 0) or (bad >= 25 and bad > good * 3):
                    raise ExampleError(
                        f"Proxy unhealthy after {index + 1} requests (ok={good} err={bad}, last={type(error).__name__})"
                    ) from error
                time.sleep(delay)
                continue

            location = response.headers.get("location") or response.headers.get("Location") or ""
            body = response.text or ""
            if "/blocked" in location.lower():
                # The 307 body is empty, the captcha markup is on the page it points at.
                blocked_url = urljoin(target.trigger_url, location)
                return self.get(blocked_url), blocked_url, index + 1
            if response.status_code in (403, 412, 429) or "px-captcha" in body.lower():
                return response, target.trigger_url, index + 1
            time.sleep(delay)

        raise ExampleError(
            f"No block after {max_reqs} requests (ok={good} err={bad}). This proxy is too clean to get flagged, try a dirtier pool."
        )

    @staticmethod
    def extract_block_params(body: str, blocked_url: str) -> dict:
        app_id = APPID_PATTERN.search(body or "")
        uuid = UUID_PATTERN.search(blocked_url or "")
        vid = VID_PATTERN.search(blocked_url or "")
        return {
            "appId": app_id.group(1) if app_id else None,
            "uuid": uuid.group(1) if uuid else "",
            "vid": vid.group(1) if vid else "",
        }

    def solve(self, app_id: str, blocked_url: str, block_html: str, on_queue=None,
              budget: float = 240) -> dict:
        endpoint = (
            f"{API_URL}/{app_id}/solve" if self.target.app_id_in_path
            else f"{API_URL}/solve"
        )

        submit = validate(parse(requests.post(
            endpoint,
            headers={"x-api-key": self.api_key},
            json={
                "proxy": self.proxy,
                "blocked_url": blocked_url,
                "appId": app_id,
                "block_response": {
                    "body": block_html,
                    "url": blocked_url,
                    "appId": app_id,
                },
            },
            timeout=30,
        ), "Takion pxhc"))

        ticket = submit.get("ticket") or submit.get("task_id")
        if not ticket:
            raise Exception(f"No ticket in submit response: {submit}")
        if on_queue:
            on_queue(ticket, submit.get("eta_s"))

        # Poll on a wall clock, a hung poll costs as much as ten that answer.
        deadline = time.time() + budget
        while time.time() < deadline:
            time.sleep(3)
            try:
                pull = parse(requests.get(
                    f"{API_URL}/solve/{ticket}",
                    headers={"x-api-key": self.api_key},
                    timeout=15,
                ), "Takion pxhc")
            except (requests.RequestException, ExampleError):
                # A poll that fails says nothing about the solve; keep waiting.
                continue
            state = pull.get("state") or pull.get("status")
            if state in ("done", "solved"):
                return pull
            if state == "error":
                validate(pull)
                raise Exception(pull.get("error", "solve error"))

        raise Exception(f"Solve did not land within {budget:.0f}s (ticket {ticket})")

    def replay(self, cookies: dict, attempts: int = 2) -> TLSResponse:
        failure = ""
        for attempt in range(1, attempts + 1):
            try:
                response = requests.get(
                    self.target.trigger_url,
                    headers=self.target.headers,
                    cookies=cookies,
                    proxies=self.proxies,
                    timeout=self.target.timeout,
                    allow_redirects=False,
                )
                return TLSResponse({
                    "status_code": response.status_code,
                    "body": response.text,
                    "headers": dict(response.headers),
                })
            except Exception as error:
                failure = f"{type(error).__name__}: {error}"
                if attempt < attempts:
                    time.sleep(2)
        raise ExampleError(
            f"Got a cookie but the replay could not run ({failure}). The proxy died after the solve, so this is not a solver verdict."
        )
