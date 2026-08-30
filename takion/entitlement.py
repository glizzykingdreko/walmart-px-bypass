
import requests

WHOAMI_URL = "https://pxhc.takionapi.tech/whoami"
DISCORD = "https://takionapi.tech/discord"
EMAIL = "hello@takionapi.tech"

# One lookup per process, the answer does not change inside a run.
_ANSWERS = {}


# Not a bypass failure and not a broken environment, so it reports as a skip.
class NotEntitled(Exception):
    pass


# Match on pieces, there are two phrasings and the "tiral" typo is theirs.
TRIAL_WORDS = ("trial", "tiral")
CONTACT_WORDS = ("discord", "contact us", "contact the")


def is_trial_limit(message: str) -> bool:
    text = (message or "").lower()
    return any(w in text for w in TRIAL_WORDS) and any(w in text for w in CONTACT_WORDS)


def contact() -> str:
    return f"Ask for access on Discord, {DISCORD}, or at {EMAIL}."


def whoami(api_key: str, timeout: int = 20) -> dict:
    if api_key in _ANSWERS:
        return _ANSWERS[api_key]

    try:
        response = requests.get(
            WHOAMI_URL, headers={"x-api-key": api_key}, timeout=timeout
        )
        answer = response.json()
        if not isinstance(answer, dict):
            answer = {}
    except Exception:
        # A lookup that cannot run tells us nothing, so it must not block a run.
        answer = {}

    _ANSWERS[api_key] = answer
    return answer


def refusal(api_key: str, app_id: str, website: str = "") -> str:
    answer = whoami(api_key)
    if not answer:
        return ""

    where = website or app_id
    if answer.get("whitelisted") is False:
        return f"This key is not whitelisted for captcha solving, so the pxhc flow cannot run against {where} (app id {app_id})."

    targets = answer.get("targets")
    if not isinstance(targets, list):
        return ""

    for target in targets:
        if not isinstance(target, dict) or target.get("app_id") != app_id:
            continue
        if target.get("authorized") is False:
            site = target.get("website") or where
            return f"This key is not cleared to solve captchas for {site} (app id {app_id})."
        return ""
    return ""


def require_target(api_key: str, app_id: str, website: str = "") -> None:
    if reason := refusal(api_key, app_id, website):
        raise NotEntitled(reason)
