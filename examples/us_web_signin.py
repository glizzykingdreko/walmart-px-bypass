import base64
import hashlib
import json
import os
import secrets
import sys
import time
from random import randint

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.queries import us_identity as Q
from takion import TakionPxWeb
from takion.common import (
    api_key, detail, find_platform_version, json_body, outcome,
    raise_if_blocked, require_env, run_example, solve_with_retry, step,
)
from takion.result import PASS

APP_ID = "PXu6b0qd2S"
CLIENT_ID = "5f3fb121-076a-45f6-9587-249f0bc160ff"
TENANT_ID = "elh9ie"
FALLBACK_PLATFORM = "usweb-1.282.0-de2b126a4b6420df1d3b23b1c21d6424704cfb48-7071527r"
TEMPO_TARGETING = "%7B%22identityClientTarget%22%3A%225f3fb121-076a-45f6-9587-249f0bc160ff%22%7D"

NAV_HEADERS = {
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "sec-fetch-site": "none",
    "sec-fetch-mode": "navigate",
    "sec-fetch-user": "?1",
    "sec-fetch-dest": "document",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "accept-language": "en-US",
    "priority": "u=0, i",
}


def b64url(n: int, lower: bool = False) -> str:
    raw = base64.urlsafe_b64encode(secrets.token_bytes(n)).rstrip(b"=").decode()
    return raw.lower() if lower else raw


def pkce_pair():
    verifier = b64url(32)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def device_ref() -> str:
    return b64url(27, lower=True).replace("_", "").replace("-", "")[:36]


def traceparent() -> str:
    return f"00-{time.time_ns() & 0xFFFFFFFFFFFFFFFF:016x}{secrets.randbits(64):016x}-{secrets.randbits(64):016x}-00"


def identity_url(path: str, challenge: str) -> str:
    redirect = "https%3A%2F%2Fwww.walmart.com%2Faccount%2FverifyToken"
    if path == "/account/login":
        qs = (f"client_id={CLIENT_ID}&redirect_uri={redirect}&scope=openid+email+offline_access&tenant_id={TENANT_ID}&state=%2F&code_challenge={challenge}")
    else:
        qs = (f"scope=openid%20email%20offline_access&redirect_uri={redirect}&client_id={CLIENT_ID}&tenant_id={TENANT_ID}&code_challenge={challenge}&state=%2F")
    return f"https://identity.walmart.com{path}?{qs}"


def sso_options(challenge: str) -> dict:
    return {
        "wasConsentCaptured": True,
        "callbackUrl": "https://www.walmart.com/account/verifyToken",
        "clientId": CLIENT_ID,
        "scope": "openid email offline_access",
        "state": "/",
        "challenge": challenge,
    }


def gql(solver, query, variables, page_url, platform_version, ref):
    parts = query.lstrip().split(None, 2)
    kind, op = parts[0], parts[1].split("(")[0].split("{")[0]
    tp = traceparent()
    cid = b64url(27)
    headers = {
        "x-o-mart": "B2C",
        "sec-ch-ua-platform": '"macOS"',
        "x-o-segment": "oaoh",
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "x-enable-server-timing": "1",
        "sec-ch-ua-mobile": "?0",
        "x-latency-trace": "1",
        "wm_mp": "true",
        "accept": "application/json",
        "accept-encoding": "gzip, deflate, br, zstd",
        "content-type": "application/json",
        "tenant-id": TENANT_ID,
        "downlink": "10",
        "x-o-platform": "rweb",
        "accept-language": "en-US",
        "x-o-ccm": "server",
        "x-o-bu": "WALMART-US",
        "dpr": "2",
        "origin": "https://identity.walmart.com",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "priority": "u=1, i",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "x-o-gql-query": f"{kind} {op}",
        "x-apollo-operation-name": op,
        "device_profile_ref_id": ref,
        "baggage": f"requestTs={int(time.time() * 1000)},tpid={tp}",
        "traceparent": tp,
        "wm_qos.correlation_id": cid,
        "x-o-correlation-id": cid,
        "x-o-platform-version": platform_version,
        "wm_page_url": page_url,
        "referer": page_url,
    }
    body = json.dumps({"query": query, "variables": variables}, separators=(",", ":"))
    return solver.post(
        "https://identity.walmart.com/orchestra/idp/graphql",
        headers,
        data=body,
    )


def main() -> int:
    key = api_key()
    email = require_env("WALMART_EMAIL")
    detail(f"email {email}")

    _, challenge = pkce_pair()

    # [1] Solve PX, rotating proxies if the pool hands us a bad exit.
    step(1, "Solving PX (Walmart US)...")
    solver, px, _ = solve_with_retry(
        lambda proxy: TakionPxWeb(key, proxy),
        lambda client: client.generate_px_session(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
            app_id=APP_ID,
            page_url="https://www.walmart.com/",
        ),
    )
    detail(f"px cookies: {[k for k in px if k != 'extra']}")
    detail(f"session -> {solver.session_id}\n")

    # [2] Page-load chain, the requests a browser makes before anyone types.
    step(2, "Page-load chain (homepage -> login page)...")
    solver.get("https://www.walmart.com/", NAV_HEADERS)
    homepage = solver.get("https://www.walmart.com/", NAV_HEADERS)
    platform_version = find_platform_version(homepage.text or "", "usweb-", FALLBACK_PLATFORM)

    xhr_headers = {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept-language": "en-US",
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": "https://www.walmart.com/",
    }
    solver.get(
        "https://www.walmart.com/orchestra/home/graphql/Location/26e4ca8c866334908ce825a5749f6aa13f772b98a527b0d0b7fe457818c5b349",
        xhr_headers,
    )
    solver.get(
        "https://b.www.walmart.com/rum.js?bh=beacon.lightest.walmart.com",
        {**xhr_headers, "sec-fetch-dest": "script"},
    )
    solver.post("https://www.walmart.com/si/elh9ie/obs", xhr_headers, data="")

    login_url = identity_url("/account/login", challenge)
    login_nav = solver.get(
        login_url,
        {**NAV_HEADERS, "sec-fetch-site": "same-site", "referer": "https://www.walmart.com/"},
    )
    raise_if_blocked(login_nav, "login page")
    platform_version = find_platform_version(login_nav.text or "", "usweb-", platform_version)
    detail(f"done. platform_version={platform_version[:26]}...\n")

    # [3] Email lookup.
    step(3, "GetLoginOptions (email lookup)...")
    ref = device_ref()
    gql(solver, Q.SHIPPING_COUNTRY_LIST, {}, login_url, platform_version, ref)
    login_options = gql(
        solver,
        Q.GET_LOGIN_OPTIONS,
        {"input": {"loginId": email, "loginIdType": "EMAIL", "ssoOptions": sso_options(challenge)}},
        login_url,
        platform_version,
        ref,
    )
    raise_if_blocked(login_options, "GetLoginOptions")
    options = (json_body(login_options).get("data") or {}).get("getLoginOptions") or {}
    detail(
        f"status={login_options.status_code} canUseEmailOTP={options.get('canUseEmailOTP')} errors={bool(options.get('errors'))}\n"
    )

    # [4] The CMS modules the SPA loads between screens.
    step(4, "Tempo modules (sign-in screens)...")
    otp_choice_url = identity_url("/account/signin/withotpchoice", challenge)
    ref = device_ref()
    tempo = {"targeting": TEMPO_TARGETING}
    gql(solver, Q.SIGNIN_OTP_CHOICE_MODULE,
        {"pageType": "SignInWithOTPChoicePage", "tenant": "WM_GLASS", "tempo": tempo},
        otp_choice_url, platform_version, ref)
    gql(solver, Q.SIGNIN_PASSWORD_ONLY_MODULE,
        {"pageType": "B2CSignInWithPasswordOnlyPage", "tenant": "WM_GLASS", "tempo": tempo},
        otp_choice_url, platform_version, ref)
    detail("loaded\n")

    # [5] Request the one-time code.
    step(5, "GenerateOtp (email)...")
    generated = gql(
        solver,
        Q.GENERATE_OTP,
        {"input": {
            "loginId": email,
            "loginIdType": "EMAIL",
            "otpOperation": "OTP_EMAIL_SIGN_IN",
            "ssoOptions": sso_options(challenge),
        }},
        otp_choice_url,
        platform_version,
        ref,
    )
    raise_if_blocked(generated, "GenerateOtp")

    generated_data = (json_body(generated).get("data") or {}).get("generateOTP") or {}
    receipt_id = (generated_data.get("otpResult") or {}).get("receiptId")
    errors = [e.get("code") for e in (generated_data.get("errors") or [])]
    detail(f"status={generated.status_code} receiptId={receipt_id} errors={errors}\n")

    if "RATE_LIMIT_EXCEEDED" in errors:
        # Being rate-limited means the session was trusted enough to rate-limit.
        detail("Reached GenerateOtp unblocked; Walmart is rate-limiting this mailbox.")
        detail("Wait a few minutes or use another mailbox to go further.")
        outcome(generated, "GenerateOtp")
        return PASS

    # [6] Code-entry screen.
    step(6, "Tempo module (code entry)...")
    otp_only_url = identity_url("/account/signin/otponly", challenge)
    ref = device_ref()
    gql(solver, Q.SIGNIN_OTP_MODULE,
        {"pageType": "SignInWithOTPOnlyPage", "tenant": "WM_GLASS", "tempo": tempo},
        otp_only_url, platform_version, ref)
    detail("loaded\n")

    # [7] Submit a random code, an OTP error back means the flow reached Walmart.
    step(7, "SignInWithOTP (random code)...")
    code = f"{randint(100000, 999999)}"
    submitted = gql(
        solver,
        Q.SIGN_IN_WITH_OTP,
        {
            "input": {
                "loginId": email,
                "loginIdType": "EMAIL",
                "otpCode": code,
                "otpOperation": "OTP_EMAIL_SIGN_IN",
                "rememberMe": True,
                "ssoOptions": sso_options(challenge),
            },
            "includePhoneInfo": True,
        },
        otp_only_url,
        platform_version,
        ref,
    )
    raise_if_blocked(submitted, "SignInWithOTP")

    submitted_data = (json_body(submitted).get("data") or {}).get("signInWithOTP") or {}
    error_codes = [e.get("code") for e in (submitted_data.get("errors") or [])]
    detail(f"status={submitted.status_code} code={code} errors={error_codes}")
    detail(f"body: {json.dumps(json_body(submitted))[:200]}")
    detail("Walmart answered the OTP submission, the session was never blocked.")
    outcome(submitted, "SignInWithOTP")
    return PASS


if __name__ == "__main__":
    raise SystemExit(run_example(main))
