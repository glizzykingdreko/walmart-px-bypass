from json import loads

import requests

from .transport import parse, validate

BASE_URL = "https://px-web.takionapi.tech"


class TLSResponse:
    def __init__(self, resp: dict):
        self.status_code = resp.get("status_code")
        self.text = resp.get("body")
        self.headers = resp.get("headers", {})
        self.raw_json = resp

    def json(self):
        return loads(self.text)


class TakionPxWeb:

    def __init__(self, api_key: str, proxy: str) -> None:
        self.api_key = api_key
        self.proxy = proxy
        self.session_id = False

    @property
    def _auth(self) -> dict:
        return {"x-api-key": self.api_key}

    def _post(self, path: str, payload: dict) -> dict:
        response = requests.post(f"{BASE_URL}{path}", headers=self._auth, json=payload)
        return validate(parse(response, "Takion px-web"))

    def send_request(
        self,
        method: str,
        url: str,
        headers: dict = None,
        data: str = None,
        json: dict = None,
        **kwargs,
    ) -> TLSResponse:
        return TLSResponse(self._post("/tls", {
            "proxy": self.proxy,
            "session_id": self.session_id,
            "method": method,
            "url": url,
            "headers": headers,
            "json": json,
            "data": data,
            **kwargs,
        }))

    def get(self, url: str, headers: dict = None, data: str = None,
            json: dict = None, **kwargs) -> TLSResponse:
        return self.send_request("GET", url, headers, data, json, **kwargs)

    def post(self, url: str, headers: dict = None, data: str = None,
             json: dict = None, **kwargs) -> TLSResponse:
        return self.send_request("POST", url, headers, data, json, **kwargs)

    def generate_px_session(
        self,
        user_agent: str,
        app_id: str = "PXu6b0qd2S",
        page_url: str = "https://www.walmart.com/",
        fast_mode: bool = True,
        **kwargs,
    ) -> dict:
        resp = self._post("/generate", {
            "proxy": self.proxy,
            "user_agent": user_agent,
            "app_id": app_id,
            "page_url": page_url,
            "fast_mode": fast_mode,
            **kwargs,
        })
        self.session_id = resp["extra"]["x-px-session-id"]
        return resp

    def set_session_cookies(self, cookies: dict, domain: str) -> dict:
        return self._post("/extra/tls/set_cookies", {
            "session_id": self.session_id,
            "cookies": cookies,
            "domain": domain,
        })

    def initialize_walmart_session(self, login_url: str, user_agent: str = None) -> dict:
        return self._post("/extra/tls/initialize_walmart", {
            "session_id": self.session_id,
            "login_url": login_url,
            "user_agent": user_agent,
        })
