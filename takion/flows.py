import time

from .common import (
    detail, is_blocked, mask_proxy, outcome, outcome_note, pick_proxy,
    require_access, step,
)
from .pxhc import TakionPxHC
from .result import FAIL, PASS, ExampleError


def run_pxhc_flow(target, proxy_attempts: int = 3, solve_attempts: int = 3, budget: float = 420) -> int:
    # The four surfaces have different app ids, so each needs its own clearance.
    key = require_access(target.app_id, target.short_url.split("/")[0])
    started = time.time()

    # [1] Hammer the trigger until PX flags this proxy.
    step(1, f"Hammering {target.short_url} until blocked...")
    solver = block_response = blocked_url = None
    requests_sent = 0
    last_error = None
    for attempt in range(1, proxy_attempts + 1):
        left = budget - (time.time() - started)
        if left < 30:
            last_error = ExampleError(
                f"ran out of time hunting for a block ({budget:.0f}s spent over {attempt - 1} proxies)"
            )
            break
        proxy = pick_proxy()
        solver = TakionPxHC(key, proxy, target)
        detail(f"[{attempt}/{proxy_attempts}] proxy {mask_proxy(proxy)}, {left:.0f}s left of the block budget")
        try:
            block_response, blocked_url, requests_sent = solver.hammer_until_blocked(
                budget=min(left, 150)
            )
            break
        except ExampleError as error:
            last_error = error
            detail(f"    {error}, rotating")
            block_response = None

    if not block_response:
        raise ExampleError(
            f"No proxy in the pool could earn a block ({last_error}). This is the pool, not the solver."
        )

    block_html = block_response.text or ""
    detail(
        f"blocked ({block_response.status_code}) after {requests_sent} requests in {time.time() - started:.0f}s"
    )
    if "px-captcha" not in block_html and "_pxAppId" not in block_html:
        raise ExampleError(
            "Triggered a block but the captcha markup is missing, the redirect was probably not followed."
        )

    params = solver.extract_block_params(block_html, blocked_url)
    app_id = params["appId"] or target.app_id
    detail(f"appId={app_id} uuid={params['uuid'] or '(none in URL)'}\n")

    # [2] Solve. A rejected verdict still returns a _px3 and it is a dud, re-solve.
    step(2, "Solving...")
    solve_started = time.time()
    for attempt in range(1, solve_attempts + 1):
        solved = solver.solve(
            app_id,
            blocked_url,
            block_html,
            on_queue=lambda ticket, eta: detail(
                f"queued ticket={ticket}" + (f" eta={eta}s" if eta else "")
            ),
        )
        verdict = solved.get("verdict")
        solve_status = solved.get("solve_status")
        detail(f"verdict={verdict} solve_status={solve_status}")
        if solve_status != -1 and verdict != "rejected":
            break
        if attempt < solve_attempts:
            detail(f"solver rejected its own solve, re-solving [{attempt}/{solve_attempts}]")

    cookies = solved.get("cookies") or {}
    px3 = cookies.get("_px3")
    # Surface count varies (advertising returns 3 cookies, www returns 5). Not a failure.
    detail(f"cookies={sorted(cookies)} in {time.time() - solve_started:.0f}s")
    if solve_status == -1 or verdict == "rejected":
        # Replay anyway, the origin gets the last word on the cookie.
        detail(f"still rejected after {solve_attempts} solves, replaying anyway")
    if not px3:
        detail(
            f"No _px3 returned: verdict={solved.get('verdict')} error={solved.get('error')} warnings={solved.get('warnings')}"
        )
        outcome_note(
            f"solve {target.short_url}",
            f"no _px3 cookie, verdict={solved.get('verdict')} solve_status={solved.get('solve_status')} error={solved.get('error')}",
        )
        return FAIL
    detail(f"_px3={px3[:40]}...\n")

    # [3] Replay the blocked request with the solved cookies.
    step(3, "Replaying the blocked request with the returned cookies...")
    replayed = solver.replay(cookies)
    # Testing for 403 alone waved through a 307 straight back to /blocked.
    accepted = not is_blocked(replayed)
    detail(f"status={replayed.status_code} -> {'ACCEPTED' if accepted else 'STILL BLOCKED'}")
    if not accepted:
        detail(f"Origin refused the cookie. solve_status={solved.get('solve_status')}")
        # A rejected solve is the actionable fact, the replay is the consequence.
        if solve_status == -1 or verdict == "rejected":
            outcome_note(
                f"solve {target.short_url}",
                f"solver rejected all {solve_attempts} solves (verdict={verdict} solve_status={solve_status}), origin refused the cookie",
                replayed.status_code,
            )
        else:
            outcome(replayed, f"replay {target.short_url}")
        return FAIL

    detail(f"blocked + solved + cookie accepted in {time.time() - started:.0f}s")
    outcome(replayed, f"replay {target.short_url}")
    return PASS
