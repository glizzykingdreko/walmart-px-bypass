import base64
import hashlib
import os
import secrets
import sys
import time
from random import randint

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from examples.queries import ca_identity as Q
from takion import TakionPxWeb
from takion.common import (
    api_key, detail, json_body, outcome, raise_if_blocked, run_example,
    solve_with_retry, step,
)
from takion.result import FAIL, PASS

APP_ID = "PXu6b0qd2S"
CLIENT_ID = "ebc4bf34-398f-4ee7-8e0c-91e8ea508158"
TENANT_ID = "qxjed8"
REDIRECT = "https%3A%2F%2Fwww.walmart.ca%2Faccount%2FverifyToken"
ACCEPT_LANG = "en-CA"
BU = "WALMART-CA"
PLATFORM_VERSION = "intlc-1.163.0-a7fba99cdc56de6908db5831d5e662e4d27f99db-6011602"


# The account being registered. Randomised so reruns do not collide.
PASSWORD = "Example0123!"
FIRST_NAME, LAST_NAME = "Luke", "Skywalker"


def b64url(n: int, lower: bool = False) -> str:
    raw = base64.urlsafe_b64encode(secrets.token_bytes(n)).rstrip(b"=").decode()
    return raw.lower() if lower else raw


def traceparent() -> str:
    return f"00-{time.time_ns():016x}{secrets.token_hex(8)}-{secrets.token_hex(8)}-00"


def page_url(path: str, challenge: str, extra: str = "") -> str:
    return (
        f"https://identity.walmart.com{path}?scope=openid%20email%20offline_access&redirect_uri={REDIRECT}&client_id={CLIENT_ID}&tenant_id={TENANT_ID}&code_challenge={challenge}&state=%2Fen&tp=GIC{extra}"
    )


def gql(solver, query, variables, url, ref):
    op_decl = query.split("(", 1)[0]
    op_name = op_decl.split()[1]
    corr = b64url(27)
    tp = traceparent()
    headers = {
        "x-o-mart": "B2C",
        "x-o-gql-query": op_decl,
        "sec-ch-ua-platform": '"macOS"',
        "x-o-segment": "oaoh",
        "device_profile_ref_id": ref,
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "x-enable-server-timing": "1",
        "sec-ch-ua-mobile": "?0",
        "baggage": f"requestTs={int(time.time() * 1000)},tpid={tp}",
        "x-latency-trace": "1",
        "traceparent": tp,
        "wm_mp": "true",
        "accept": "application/json",
        "content-type": "application/json",
        "x-apollo-operation-name": op_name,
        "tenant-id": TENANT_ID,
        "downlink": "10",
        "wm_qos.correlation_id": corr,
        "x-o-platform": "rweb",
        "x-o-platform-version": PLATFORM_VERSION,
        "accept-language": ACCEPT_LANG,
        "x-o-ccm": "server",
        "x-o-bu": BU,
        "dpr": "2",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "wm_page_url": url,
        "x-o-correlation-id": corr,
        "origin": "https://identity.walmart.com",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": url,
        "accept-encoding": "gzip, deflate, br, zstd",
        "priority": "u=1, i",
    }
    return solver.post(
        "https://identity.walmart.com/orchestra/graphql",
        headers,
        json={"operationName": op_name, "variables": variables, "query": query},
    )


def signup_input(email, phone, sso, step_up=None) -> dict:
    payload = {
        "loginId": email,
        "loginIdType": "EMAIL",
        "password": PASSWORD,
        "firstName": FIRST_NAME,
        "lastName": LAST_NAME,
        "rememberMe": True,
        "marketingEmailsAccepted": False,
        "phoneNumber": phone,
        "nonProfilePhoneNumber": {"number": phone, "countryCode": "+1", "isoCountryCode": "CA"},
        "ssoOptions": sso,
    }
    if step_up:
        payload["emailId"] = email
        payload["nonProfilePhoneNumber"] = {"number": phone, "countryCode": "1", "isoCountryCode": "CA"}
        payload["stepUpOptions"] = step_up
        payload["gepAdditionalInfo"] = {
            "disclaimerText": "By clicking Continue, you acknowledge you have read and agreed to our Terms of Use and Privacy Policy.",
            "moduleId": "98cea575-636c-408d-970d-77ef55279c76",
            "moduleVersion": "4",
        }
    return payload


def main() -> int:
    key = api_key()

    email = f"coral{randint(10**7, 10**8)}@gmail.com"
    phone = f"416{randint(2000000, 9999999)}"
    otp = os.getenv("WALMART_SIGNUP_OTP", "")
    detail(f"email {email}")
    detail(f"phone {phone}")

    verifier = b64url(32)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    login_page = (
        f"https://identity.walmart.com/en/account/login?tp=GIC&client_id={CLIENT_ID}&redirect_uri={REDIRECT}&scope=openid+email+offline_access&tenant_id={TENANT_ID}&state=%2Fen&code_challenge={challenge}"
    )
    sso = {
        "wasConsentCaptured": True,
        "callbackUrl": "https://www.walmart.ca/account/verifyToken",
        "clientId": CLIENT_ID,
        "scope": "openid email offline_access",
        "state": "/en",
        "challenge": challenge,
    }

    # [1] Solve PX. fast_mode off, sign-up is scored harder than browsing.
    step(1, "Solving PX (Walmart CA, full mode)...")
    solver, px, _ = solve_with_retry(
        lambda proxy: TakionPxWeb(key, proxy),
        lambda client: client.generate_px_session(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
            app_id=APP_ID,
            page_url=login_page,
            fast_mode=False,
        ),
    )
    detail(f"px cookies: {[k for k in px if k != 'extra']}")
    detail(f"session -> {solver.session_id}\n")

    # [2] Login page + bootstrap config.
    step(2, "GET login page + bootstrap...")
    login_response = solver.get(login_page, {
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "navigate",
        "sec-fetch-dest": "document",
        "accept-language": f"{ACCEPT_LANG},en;q=0.9",
        "referer": "https://identity.walmart.com/",
    })
    raise_if_blocked(login_response, "login page")
    detail(f"login page -> {login_response.status_code}")

    bootstrap = solver.get(
        "https://identity.walmart.com/orchestra/api/ccm/v3/bootstrap?configNames=identity,pulse,shared,footer,account",
        {
            "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
            "accept": "application/json",
            "wm_mp": "true",
            "x-o-platform": "rweb",
            "x-o-bu": BU,
            "tenant-id": TENANT_ID,
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "accept-language": f"{ACCEPT_LANG},en;q=0.9",
            "referer": login_page,
        },
    )
    detail(f"bootstrap -> {bootstrap.status_code}\n")

    # [3] Email lookup, confirms the address is not already registered.
    step(3, "GetLoginOptions...")
    ref_login = b64url(27, lower=True)
    login_opts = gql(
        solver,
        Q.GET_LOGIN_OPTIONS,
        {"input": {"loginId": email, "loginIdType": "EMAIL", "ssoOptions": sso}},
        login_page,
        ref_login,
    )
    raise_if_blocked(login_opts, "GetLoginOptions")
    detail(f"status={login_opts.status_code} {(login_opts.text or '')[:80]}\n")

    # [4] SignUp, submits the account and asks for phone verification.
    step(4, "SignUp (initiate)...")
    ref_signup = b64url(27, lower=True)
    signup1 = gql(
        solver,
        Q.SIGN_UP,
        {"input": signup_input(email, phone, sso)},
        page_url("/account/signup", challenge),
        ref_signup,
    )
    raise_if_blocked(signup1, "SignUp (initiate)")
    detail(f"status={signup1.status_code} {(signup1.text or '')[:80]}\n")

    # [5] GenerateOtp, fires the SMS and returns the receiptId.
    step(5, "GenerateOtp (SMS)...")
    gen_otp = gql(
        solver,
        Q.GENERATE_OTP,
        {"input": {
            "otpChannel": "PHONE_TEXT",
            "loginId": email,
            "loginIdType": "EMAIL",
            "nonProfilePhoneNumber": {"number": phone, "countryCode": "+1", "isoCountryCode": "CA"},
            "otpOperation": "OTP_UNREGISTERED_USER_PHONE_VERIFY",
            "phoneNumber": phone,
            "ssoOptions": sso,
        }},
        page_url("/account/phone-otp-choice/sign-up", challenge),
        ref_signup,
    )
    raise_if_blocked(gen_otp, "GenerateOtp")
    detail(f"status={gen_otp.status_code} {(gen_otp.text or '')[:80]}\n")

    # [6] SignUp again with the code. Needs a real SMS to actually register.
    step(6, "SignUp (complete)...")
    ref_verify = b64url(27, lower=True)
    signup2 = gql(
        solver,
        Q.SIGN_UP,
        {"input": signup_input(email, phone, sso, step_up={
            "nonProfilePhoneNumber": {"number": phone, "countryCode": "1", "isoCountryCode": "CA"},
            "phoneNumber": phone,
            "otpCode": otp or "000000",
            "otpOperation": "OTP_UNREGISTERED_USER_PHONE_VERIFY",
        })},
        page_url("/account/verifyyouraccount", challenge),
        ref_verify,
    )
    raise_if_blocked(signup2, "SignUp (complete)")

    detail(f"status={signup2.status_code} {(signup2.text or '')[:120]}\n")
    if otp:
        errors = ((json_body(signup2).get("data") or {}).get("signUp") or {}).get("errors") or []
        if errors:
            detail(f"Sign-up rejected: {[e.get('code') for e in errors]}")
            outcome(signup2, "SignUp (complete)")
            return FAIL
        detail(f"Account created: {email}")
    else:
        detail("No OTP supplied, so this stopped at the verification step as expected.")
        detail("Set WALMART_SIGNUP_OTP in .env to complete a real registration.")
    outcome(signup2, "SignUp (complete)")
    return PASS


if __name__ == "__main__":
    raise SystemExit(run_example(main))
