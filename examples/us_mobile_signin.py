import json
import os
import sys
import uuid
from hashlib import md5
from time import time
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from takion import TakionPxMobile
from takion.common import (
    api_key, detail, json_body, outcome, raise_if_blocked, require_env,
    run_example, solve_with_retry, step,
)
from takion.result import FAIL, PASS

PACKAGE_NAME = "com.walmart.android"
CLIENT_ID = "5f3fb121-076a-45f6-9587-249f0bc160ff"

# Persisted-query hashes for the Android client, rotate with app releases.
H_COUNTRY_LIST = "d270d2f0176c16427cebb7b78860dab7f93e7f605d8a2303f9f734ed2caaa77c"
H_GET_LOGIN_OPTIONS = "c63294f3521cc9054a53cca1dd788805d0bb0039200d6ac0032dfa5ea0d69aab"
H_SIGN_IN_V2 = "dcafda177d25dab8a6fd25794f49eb0206cfbee3597f9b21f7aea535b466ec89"

SSO_OPTIONS = {
    "callbackUrl": "https://www.walmart.com/verifyToken",
    "clientId": CLIENT_ID,
    "nonce": "RECOMMENDED",
    "scope": "openid email offline_access",
    "state": "",
    "wasConsentCaptured": False,
}


def px_headers(px: dict) -> dict:
    return {
        "X-PX-VID": px["x-px-vid"],
        "X-PX-OS-VERSION": px["x-px-os-version"],
        "X-PX-UUID": px["x-px-uuid"],
        "X-PX-DEVICE-FP": px["x-px-device-fp"],
        "X-PX-DEVICE-MODEL": px["x-px-device-model"],
        "X-PX-OS": px["x-px-os"],
        "X-PX-MOBILE-SDK-VERSION": px["x-px-mobile-sdk-version"],
        "X-PX-AUTHORIZATION": px["x-px-authorization"],
    }


def base_headers(px: dict, op_id: str, op_name: str, op_type: str) -> dict:
    return {
        "X-APOLLO-OPERATION-ID": op_id,
        "X-APOLLO-OPERATION-NAME": op_name,
        "Accept": "multipart/mixed; deferSpec=20220824, application/json",
        "X-APOLLO-CACHE-OPERATION-TYPE": op_type,
        "X-APOLLO-CACHE-FETCH-POLICY": "NETWORK_ONLY",
        "X-APOLLO-CACHE-DO-NOT-STORE": "true",
        "X-APOLLO-CACHE-KEY": md5((op_name + op_id).encode()).hexdigest(),
        "User-Agent": px["user-agent"],
        "Accept-Language": "es-US",
        "x-o-mart": "B2C",
        "x-o-bu": "WALMART-US",
        "x-o-segment": "oaoh",
        "x-o-platform": px["x-o-platform"],
        "x-o-platform-version": px["x-o-platform-version"],
        "x-wm-sid": px["x-wm-sid"],
        "x-wm-vid": px["x-wm-vid"],
        "x-o-device-id": px["x-o-device-id"],
        # Coarse install date, the app rounds it, so a precise value stands out.
        "x-o-fuzzy-install-date": str(int(time() * 1000 // 100000000) * 100000000),
        "traceparent": px["traceparent"],
        "baggage": f"deviceType=Android,trafficType=release,requestTs={int(time() * 1000)}",
        "tenant-id": "elh9ie",
        **px_headers(px),
    }


def main() -> int:
    key = api_key()
    email = require_env("WALMART_EMAIL")
    password = require_env("WALMART_PASSWORD")
    detail(f"email {email}")

    # [1] Generate the PX mobile header set and its matching device identity.
    step(1, "Generating PX headers (Android app)...")
    solver, px, _ = solve_with_retry(
        lambda proxy: TakionPxMobile(key, proxy),
        lambda client: client.generate_px_headers(PACKAGE_NAME),
    )
    detail(f"user-agent={px['user-agent'][:40]}...")
    detail(f"device={px['x-px-device-model']} android={px['x-px-os-version']}")
    detail(f"session -> {solver.session_id}\n")

    # [2] CountryList, the app's first call on launch, and a cheap PX check.
    step(2, "GET CountryList...")
    country = solver.get(
        f"https://www.walmart.com/orchestra/aroundme/graphql/CountryList/{H_COUNTRY_LIST}?variables=%7B%7D",
        headers={
            **base_headers(px, H_COUNTRY_LIST, "CountryList", "query"),
            "X-APOLLO-CACHE-KEY": "9e948c81165d2d1ed215458ae230ac67",
        },
    )
    raise_if_blocked(country, "CountryList")
    detail(f"status={country.status_code} {(country.text or '')[:100]}\n")

    # [3] GetLoginOptions, email lookup.
    step(3, "GET GetLoginOptions...")
    variables = json.dumps(
        {"input": {"loginId": email, "loginIdType": "EMAIL", "ssoOptions": SSO_OPTIONS}},
        separators=(",", ":"),
    )
    login_options = solver.get(
        f"https://www.walmart.com/orchestra/account/graphql/GetLoginOptions/{H_GET_LOGIN_OPTIONS}?variables={quote(variables)}",
        headers={
            **base_headers(px, H_GET_LOGIN_OPTIONS, "GetLoginOptions", "query"),
            "x-enable-server-timing": "1",
            "x-latency-trace": "1",
            "device_profile_ref_id": str(uuid.uuid4()),
        },
    )
    raise_if_blocked(login_options, "GetLoginOptions")
    detail(f"status={login_options.status_code} {(login_options.text or '')[:100]}\n")

    # [4] SignInV2, a real password login.
    step(4, "POST SignInV2...")
    sign_in = solver.post(
        f"https://www.walmart.com/orchestra/account/graphql/SignInV2/{H_SIGN_IN_V2}",
        headers={
            **base_headers(px, H_SIGN_IN_V2, "SignInV2", "mutation"),
            "x-enable-server-timing": "1",
            "x-latency-trace": "1",
            "device_profile_ref_id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
        json={
            "operationName": "SignInV2",
            "variables": {
                "input": {
                    "loginId": email,
                    "loginIdType": "EMAIL",
                    "password": password,
                    "rememberMe": True,
                    "ssoOptions": {**SSO_OPTIONS, "challenge": "testchallenge"},
                },
                "shouldFetchLoginOption": False,
                "shouldFetchPhoneInfo": False,
            },
            "extensions": {
                "persistedQuery": {"version": 1, "sha256Hash": H_SIGN_IN_V2},
            },
        },
    )
    raise_if_blocked(sign_in, "SignInV2")

    detail(f"status={sign_in.status_code} {(sign_in.text or '')[:200]}")

    # GraphQL answering at all means PX was cleared, whatever it answers with.
    data = json_body(sign_in).get("data")
    result = (data or {}).get("signInV2")
    if not isinstance(result, dict):
        # No signInV2 means we never reached the operation, likely a rotated hash.
        detail("No signInV2 in the response, the persisted-query hash may have rotated.")
        outcome(sign_in, "SignInV2")
        return FAIL

    errors = [e.get("code") for e in (result.get("errors") or [])]
    if result.get("auth"):
        detail("Signed in, PX cleared and Walmart accepted the credentials.")
    elif "STEP_UP_REQUIRED" in errors:
        detail(f"PX cleared. Walmart trusts the session and wants a second factor ({', '.join(errors)}), expected for a password login on a fresh device.")
    else:
        detail(f"PX cleared. Walmart answered SignInV2 at the application layer: {', '.join(errors) or 'no error, no auth token'}.")
    outcome(sign_in, "SignInV2")
    return PASS


if __name__ == "__main__":
    raise SystemExit(run_example(main))
