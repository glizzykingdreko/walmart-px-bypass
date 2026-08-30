from json import JSONDecodeError

from .entitlement import NotEntitled, is_trial_limit
from .result import ExampleError

# Statuses that mean the request never reached the solver.
INFRA_STATUS = (429, 500, 502, 503, 504)


def parse(response, what: str = "Takion API") -> dict:
    try:
        payload = response.json()
    except (JSONDecodeError, ValueError):
        payload = None

    if isinstance(payload, dict):
        return payload

    if response.status_code in INFRA_STATUS:
        raise ExampleError(
            f"{what} returned HTTP {response.status_code}. The service is rate limiting or unavailable, this is not a solve failure. Body: {(response.text or '')[:200]}"
        )
    raise ExampleError(
        f"{what} returned HTTP {response.status_code} with a non-JSON body, so the request did not reach the solver. Body: {(response.text or '')[:200]}"
    )


def validate(payload: dict) -> dict:
    if error := payload.get("error"):
        # A trial that does not cover this service is a skip, not a solve failure.
        if is_trial_limit(error):
            raise NotEntitled(error)
        # `note` is usually "proxy too slow", worth surfacing, not a solve failure.
        if note := payload.get("note"):
            raise Exception(f"{error} ({note})")
        raise Exception(error)
    return payload
