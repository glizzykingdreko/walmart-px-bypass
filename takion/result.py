# A 1 means look at this flow, a 2 means look at your proxies and .env.
PASS = 0
FAIL = 1
ERROR = 2

LABELS = {PASS: "PASS", FAIL: "FAIL", ERROR: "ERROR"}


# Environment problems: dead proxy, bad API key, missing config. Reported as ERROR.
class ExampleError(Exception):
    pass


# PX turned a request away. Says nothing about the flow, so it gets another proxy.
class Blocked(Exception):
    pass


def label(code: int) -> str:
    return LABELS.get(code, f"EXIT{code}")
