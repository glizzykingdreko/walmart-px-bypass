from json import loads
from typing import Union

import requests
from pydantic import BaseModel

from .transport import parse, validate

BASE_URL = "https://px-mobile.takionapi.tech"


class Device(BaseModel):
    manufacturer: Union[str, bool] = False
    android_version: Union[str, bool] = False
    continent: Union[str, bool] = False
    language: Union[str, bool] = False


class TLSResponse:
    def __init__(self, resp: dict):
        self.status_code = resp.get("status_code")
        self.text = resp.get("body")
        self.headers = resp.get("headers", {})
        self.raw_json = resp

    def json(self):
        return loads(self.text)


class TakionPxMobile:

    def __init__(self, api_key: str, proxy: str) -> None:
        self.api_key = api_key
        self.proxy = proxy
        self.session_id = False

    def _post(self, path: str, payload: dict) -> dict:
        # This service authenticates by query param, not header.
        response = requests.post(
            f"{BASE_URL}{path}",
            params={"api_key": self.api_key},
            json=payload,
        )
        return validate(parse(response, "Takion px-mobile"))

    def send_request(
        self,
        method: str,
        url: str,
        headers: dict = None,
        data: str = None,
        json: dict = None,
        **kwargs,
    ) -> TLSResponse:
        return TLSResponse(self._post("/mobile/tls", {
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

    def generate_px_headers(
        self,
        package_name: str,
        device: Device = None,
        **kwargs,
    ) -> dict:
        device = device or Device()
        resp = self._post("/generate", {
            "package_name": package_name,
            "proxy": self.proxy,
            **device.model_dump(),
            **kwargs,
        })
        self.session_id = resp["x-px-session-id"]
        return resp
