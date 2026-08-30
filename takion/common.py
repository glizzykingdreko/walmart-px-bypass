
import json
import os
import re
from random import choice

import requests
from dotenv import load_dotenv

from .entitlement import NotEntitled, contact, require_target
from .pxhc import proxy_url
from .result import ERROR, FAIL, PASS, Blocked, ExampleError, label

# Repo root, so an example runs the same from anywhere.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(ROOT, ".env"))

PROXY_FILE = os.path.join(ROOT, "proxies.txt")

# PX serves the interstitial on these, and GraphQL hides a /blocked in a 200.
BLOCK_STATUS = (307, 403, 412, 418, 429)

# API errors about your proxy, not the solve. A fresh exit usually clears them.
PROXY_ERROR_HINTS = (
    "proxy",
    "timeout",
    "timed out",
    "connection",
    "unreachable",
    "econnreset",
    "tunnel",
    "error making request",
)

# Errors that mean your key is wrong or out of balance.
AUTH_ERROR_HINTS = (
    "api key",
    "api_key",
    "unauthorized",
    "forbidden",
    "invalid key",
    "balance",
    "credit",
    "subscription",
    "plan",
)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ExampleError(
            f"Missing {name}. Copy .env.example to .env and fill it in."
        )
    return value


def api_key() -> str:
    return require_env("TAKION_API_KEY")


def require_access(app_id: str, website: str = "") -> str:
    key = api_key()
    require_target(key, app_id, website)
    return key


def load_proxies() -> list:
    if not os.path.exists(PROXY_FILE):
        raise ExampleError(
            "No proxies.txt. Create one at the repo root with a proxy per line:\n    host:port\n    host:port:user:pass"
        )
    pool = [line.strip() for line in open(PROXY_FILE) if line.strip()]
    if not pool:
        raise ExampleError("proxies.txt is empty.")
    return pool


def pick_proxy() -> str:
    return choice(load_proxies())


def mask_proxy(proxy: str) -> str:
    host = (proxy or "").split(":")[0]
    return f"{host}:****"


def is_proxy_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(hint in message for hint in PROXY_ERROR_HINTS)


def classify_api_error(error: Exception) -> int:
    if is_proxy_error(error):
        return ERROR
    if any(hint in str(error).lower() for hint in AUTH_ERROR_HINTS):
        return ERROR
    return FAIL


# What a proxy gateway's own status code is actually telling you.
GATEWAY_STATUS = {
    402: "Payment Required, the proxy account is out of balance or bandwidth",
    403: "Forbidden, the gateway refused these credentials",
    407: "Proxy Authentication Required, the user or password is wrong",
    429: "Too Many Requests, the proxy account is being rate limited",
}


def probe_proxy(proxy: str) -> str:
    try:
        response = requests.get(
            "http://api.ipify.org",
            proxies={"http": proxy_url(proxy), "https": proxy_url(proxy)},
            timeout=20,
        )
    except Exception as error:
        return f"could not reach the proxy gateway at all ({type(error).__name__})"

    status = response.status_code
    if status == 200:
        return f"the gateway is healthy (exit IP {(response.text or '').strip()[:40]})"
    known = GATEWAY_STATUS.get(status)
    return f"the gateway replied HTTP {status}" + (f", {known}" if known else "")


def solve_with_retry(build, solve, attempts: int = 3):
    last = None
    last_proxy = None
    for attempt in range(1, attempts + 1):
        proxy = pick_proxy()
        detail(f"[{attempt}/{attempts}] proxy {mask_proxy(proxy)}")
        solver = build(proxy)
        try:
            return solver, solve(solver), proxy
        except ExampleError as error:
            # A 5xx or non-JSON body from Takion, a transient gateway hiccup.
            last = error
            last_proxy = proxy
            detail(f"    {error}, retrying")
        except Exception as error:
            if classify_api_error(error) != ERROR:
                raise
            last = error
            last_proxy = proxy
            detail(f"    {error}, rotating")

    # The API only ever says "check your proxy", so ask the gateway itself.
    verdict = probe_proxy(last_proxy)
    raise ExampleError(
        f"No proxy in the pool produced a session after {attempts} attempts (last: {last}).\n    Checked the proxy directly: {verdict}."
    )


def is_blocked(response) -> bool:
    if response is None:
        return True
    headers = getattr(response, "headers", None) or {}
    location = headers.get("location") or headers.get("Location") or ""
    if "/blocked" in location.lower():
        return True
    if response.status_code in BLOCK_STATUS:
        return True
    body = response.text or ""
    try:
        redirect = (json.loads(body) or {}).get("redirectUrl") or ""
    except Exception:
        redirect = ""
    if "/blocked" in redirect:
        return True
    return "px-captcha" in body.lower()


def raise_if_blocked(response, where: str) -> None:
    if not is_blocked(response):
        return
    status = getattr(response, "status_code", None) or "no response"
    raise Blocked(f"{where} was blocked by PX (status={status})")


def find_platform_version(html: str, prefix: str, fallback: str) -> str:
    match = re.search(rf'"appVersion"\s*:\s*"({re.escape(prefix)}[^"]+)"', html or "")
    return match.group(1) if match else fallback


def json_body(response) -> dict:
    try:
        return json.loads(response.text or "{}")
    except Exception:
        return {}


# The runner greps this line and repeats it under the summary row.
OUTCOME_PREFIX = "[=] "


def preview(response, width: int = 120) -> str:
    body = (getattr(response, "text", "") or "").strip()
    if not body:
        return "empty body"
    if body.startswith("<"):
        title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
        named = f", title {' '.join(title.group(1).split())!r}" if title else ""
        return f"{len(body)} bytes of HTML{named}"
    collapsed = " ".join(body.split())
    return collapsed[:width] + ("..." if len(collapsed) > width else "")


def outcome(response, what: str) -> None:
    status = getattr(response, "status_code", None)
    outcome_note(what, preview(response), status)


def outcome_note(what: str, detail: str, status=None) -> None:
    print(f"{OUTCOME_PREFIX}{what} -> {status if status is not None else '-'}, {detail}")


def step(number, message: str) -> None:
    print(f"[{number}] {message}")


def detail(message: str) -> None:
    print(f"    {message}")


def run_example(main, attempts: int = 3) -> int:
    import traceback

    for attempt in range(1, attempts + 1):
        last = attempt == attempts

        def again(reason: str) -> bool:
            if last:
                return False
            print(f"\n    {reason}, retrying on a fresh proxy [{attempt}/{attempts}]\n")
            return True

        try:
            code = main()
        except Blocked as error:
            if again(f"blocked ({error})"):
                continue
            print(f"\n[{label(FAIL)}] {error}")
            print(f"    Blocked on all {attempts} attempts. Either the pool is burned on this surface,")
            print("    or this is the pxhc (captcha) path, see examples/pxhc_*.py.")
            return FAIL
        except NotEntitled as error:
            # Not a bypass failure: the run never had the entitlement to try.
            print(f"\n[SKIP] {error}")
            print(f"    {contact()}")
            return ERROR
        except ExampleError as error:
            print(f"\n[{label(ERROR)}] {error}")
            return ERROR
        except KeyboardInterrupt:
            print(f"\n[{label(ERROR)}] interrupted")
            return ERROR
        except Exception as error:
            if is_proxy_error(error) and again(f"the exit died mid-flow ({error})"):
                continue
            code = classify_api_error(error)
            if code == ERROR:
                print(f"\n[{label(ERROR)}] {error}")
            else:
                traceback.print_exc()
                print(f"\n[{label(FAIL)}] {type(error).__name__}: {error}")
            return code

        if code is None:
            code = PASS
        if code == FAIL and again("the flow did not reach its goal"):
            continue
        if code == FAIL:
            print(f"\n[{label(FAIL)}] failed on all {attempts} attempts, so this is the flow and not the pool.")
            return FAIL
        print(f"\n[{label(code)}]")
        return code
