#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# Our summary must not sit in a buffer, or it lands before the run it summarises.
sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

from takion.common import OUTCOME_PREFIX
from takion.entitlement import WHOAMI_URL, contact, refusal, whoami
from takion.result import ERROR, FAIL, PASS

ROOT = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(ROOT, "examples")

# The runner reads .env too, to know what is configured before spending solves.
load_dotenv(os.path.join(ROOT, ".env"))

# SKIP is the runner's own, for an example it never bothered to start.
QUEUED, RUNNING, SKIP = "queued", "running", "skip"


# ------ Terminal --------------------------------------------------------------

TTY = sys.stdout.isatty() and not os.getenv("NO_COLOR")
WIDTH = shutil.get_terminal_size((100, 24)).columns


def paint(text: str, *codes: str) -> str:
    if not TTY or not codes:
        return text
    return f"\033[{';'.join(codes)}m{text}\033[0m"


DIM, BOLD = "2", "1"
GREEN, RED, YELLOW, BLUE, GREY = "32", "31", "33", "36", "90"

# All four characters wide, so the name column lines up whatever the verdicts are.
MARKS = {
    PASS: ("PASS", GREEN),
    FAIL: ("FAIL", RED),
    ERROR: ("ERR!", YELLOW),
    RUNNING: ("    ", BLUE),
    QUEUED: ("    ", GREY),
    SKIP: ("SKIP", GREY),
}

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# "  MARK  " before the name column, which is where a row's detail lines hang.
GUTTER = 8
PAGE = 96


def plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def fit(text: str, room: int) -> str:
    room = max(20, room)
    return text if len(text) <= room else text[:room - 1] + "…"


# "GetLoginOptions -> 200, {"data":...}" as the examples print it.
OUTCOME_SHAPE = re.compile(r"^(?P<what>.+?) -> (?P<status>\S+), (?P<body>.*)$", re.S)


def detail_line(text: str, indent: int = GUTTER) -> str:
    shape = OUTCOME_SHAPE.match(text)
    room = min(WIDTH, PAGE) - indent - 2
    if not shape:
        return " " * indent + paint("└ " + fit(text, room), GREY)

    what, status, body = shape["what"], shape["status"], shape["body"]
    happy = status[:1] in "23"
    head = f"{what} {status}"
    return (" " * indent + paint("└ ", GREY) + paint(what + " ", GREY)
            + paint(status, GREEN if happy else YELLOW)
            + paint("  " + fit(body, room - len(head) - 2), GREY))


def wrapped(text: str, indent: int = 2) -> str:
    import textwrap

    pad = " " * indent
    lines = textwrap.wrap(text, width=min(WIDTH, PAGE) - indent) or [""]
    return "\n".join(paint(pad + line, DIM) for line in lines)


def rule(title: str = "", badge: str = "") -> str:
    head = f"── {title} " if title else "── "
    if badge:
        head += f"{badge} "
    bar = "─" * max(0, min(WIDTH, PAGE) - len(head))
    return paint(head + bar, GREY)


# ------ Registry --------------------------------------------------------------


class Example:
    def __init__(self, name, title, tags, needs=(), app_id="", website=""):
        self.name = name
        self.title = title
        self.tags = set(tags)
        self.needs = needs
        # Set on the pxhc examples only, /whoami covers captcha solving and nothing else.
        self.app_id = app_id
        self.website = website
        # Filled in by the runner.
        self.state = QUEUED
        self.code = None
        self.started = None
        self.elapsed = 0.0
        self.output = ""
        self.note = ""
        # The `[=] ...` line the example printed about its decisive response.
        self.outcome = ""
        # The step it is on, so a long row says what it is waiting for.
        self.stage = ""
        # "env", not configured, or "stopped", --stop-on-fail cut the run short.
        self.skip_reason = ""

    @property
    def path(self):
        return os.path.join(EXAMPLES, f"{self.name}.py")

    @property
    def missing_env(self) -> list:
        return [name for name in self.needs if not os.getenv(name)]


# tags: region (us/ca), surface (web/mobile), kind (init/pxhc). App ids are pxhc only.
US, CA, ADS = "PXu6b0qd2S", "PXnp9B16Cq", "PXZiTus4E5"

REGISTRY = [
    Example("us_web_atc", "US web, add to cart", ["us", "web", "init"]),
    Example("us_web_signin", "US web, sign in (email OTP)", ["us", "web", "init"],
            needs=["WALMART_EMAIL"]),
    Example("us_mobile_signin", "US mobile, sign in (password)", ["us", "mobile", "init"],
            needs=["WALMART_EMAIL", "WALMART_PASSWORD"]),
    Example("us_web_password_signin", "US web, sign in (password)", ["us", "web", "init"],
            needs=["WALMART_EMAIL", "WALMART_PASSWORD"]),
    Example("ca_web_atc", "CA web, add to cart", ["ca", "web", "init"]),
    Example("ca_web_account_create", "CA web, create an account", ["ca", "web", "init"]),
    Example("pxhc_us_web", "pxhc, www.walmart.com", ["us", "web", "pxhc"],
            app_id=US, website="www.walmart.com"),
    Example("pxhc_ca_web", "pxhc, www.walmart.ca", ["ca", "web", "pxhc"],
            app_id=CA, website="www.walmart.ca"),
    Example("pxhc_identity", "pxhc, identity.walmart.com", ["us", "web", "pxhc"],
            app_id=US, website="identity.walmart.com"),
    Example("pxhc_advertising", "pxhc, advertising.walmart.com", ["us", "web", "pxhc"],
            app_id=ADS, website="advertising.walmart.com"),
]

FILTERS = ["us", "ca", "web", "mobile", "init", "pxhc"]


def select(args) -> list:
    chosen = [f for f in FILTERS if getattr(args, f)]
    picked = REGISTRY

    if args.names:
        wanted = set(args.names)
        picked = [e for e in REGISTRY if e.name in wanted]
        missing = wanted - {e.name for e in picked}
        if missing:
            print(f"Unknown example(s): {', '.join(sorted(missing))}")
            print("Run `python run.py --list` to see the names.")
            raise SystemExit(ERROR)
    elif chosen:
        picked = [e for e in REGISTRY if set(chosen) <= e.tags]

    return picked


def print_list() -> None:
    print(f"\n{paint('Examples', BOLD)}\n")
    width = max(len(e.name) for e in REGISTRY)
    for example in REGISTRY:
        tags = paint(",".join(sorted(example.tags)), BLUE)
        needs = example.needs and paint(f"  needs {', '.join(example.needs)}", YELLOW) or ""
        print(f"  {example.name:<{width}}  {example.title:<34} {tags}{needs}")
    print(f"\n  {paint('Filters', DIM)}  {' '.join('--' + f for f in FILTERS)}")
    print(f"  {paint('Jobs   ', DIM)}  --jobs N, --serial\n")


# ------ The live board --------------------------------------------------------


class Board:
    def __init__(self, examples: list):
        self.examples = examples
        self.width = max(len(e.name) for e in examples)
        self.drawn = 0
        self.frame = 0
        self.lock = threading.Lock()

    def row(self, example) -> str:
        state = example.state if example.code is None else example.code
        mark, colour = MARKS[state]
        if state == RUNNING:
            mark = f" {SPINNER[self.frame % len(SPINNER)]}  "
        timing = "     -"
        if example.state == RUNNING:
            timing = f"{time.time() - example.started:5.1f}s"
        elif example.code is not None:
            timing = f"{example.elapsed:5.1f}s"
        elif state == QUEUED:
            timing = "      "
        trailing = example.stage if example.state == RUNNING and example.stage \
            else (example.note or example.title)
        return f"  {paint(mark, colour, BOLD)}  {example.name:<{self.width}}  {paint(timing, DIM)}  {paint(trailing, DIM)}"

    def draw(self) -> None:
        if not TTY:
            return
        with self.lock:
            if self.drawn:
                sys.stdout.write(f"\033[{self.drawn}A")
            for example in self.examples:
                sys.stdout.write("\033[2K" + self.row(example) + "\n")
            sys.stdout.flush()
            self.drawn = len(self.examples)
            self.frame += 1

    def line(self, example) -> None:
        if TTY:
            return
        print(self.row(example), flush=True)

    def clear(self) -> None:
        if not TTY or not self.drawn:
            return
        with self.lock:
            sys.stdout.write(f"\033[{self.drawn}A" + "\033[2K\n" * self.drawn)
            sys.stdout.write(f"\033[{self.drawn}A")
            sys.stdout.flush()
            self.drawn = 0


# ------ Running ---------------------------------------------------------------


def last_outcome(output: str) -> str:
    found = ""
    for line in (output or "").splitlines():
        if line.startswith(OUTCOME_PREFIX):
            found = line[len(OUTCOME_PREFIX):].strip()
    return found


# The numbered step headers. The closing "[=] ..." line is the result, not a step.
STEP_SHAPE = re.compile(r"^\[\d+\] (.+)$")


def skip_reason_in(output: str) -> str:
    for line in (output or "").splitlines():
        if line.startswith("[SKIP] "):
            return line[len("[SKIP] "):].strip()
    return ""


def stream(example, timeout: int) -> int:
    # Without PYTHONUNBUFFERED the child block-buffers and nothing arrives until it exits.
    process = subprocess.Popen(
        [sys.executable, example.path],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    lines = []

    def pump():
        for line in process.stdout:
            lines.append(line)
            if shape := STEP_SHAPE.match(line.strip()):
                example.stage = fit(shape.group(1), 46)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise
    finally:
        reader.join(timeout=5)
        example.output = "".join(lines)
        example.stage = ""
    return process.returncode


def run_one(example, timeout: int, board, stop: threading.Event) -> None:
    if stop.is_set():
        example.state = SKIP
        example.skip_reason = "stopped"
        example.note = "not started, an earlier example failed"
        return

    example.state = RUNNING
    example.started = time.time()
    try:
        code = stream(example, timeout)
    except subprocess.TimeoutExpired:
        example.note = f"timed out after {timeout}s"
        code = ERROR
    # A crash the example did not classify (segfault, killed) is an ERROR.
    if code not in (PASS, FAIL, ERROR):
        example.note = f"exited {code}"
        code = ERROR

    example.elapsed = time.time() - example.started
    # px-web and px-mobile only reveal a trial limit once you call them.
    refused = skip_reason_in(example.output)
    if refused:
        example.state = SKIP
        example.skip_reason = "access"
        example.note = refused
        board.line(example)
        return
    example.code = code
    example.state = None
    example.outcome = last_outcome(example.output)
    if not example.note:
        example.note = example.title
    board.line(example)


def execute(picked: list, jobs: int, timeout: int, stop_on_fail: bool) -> None:
    board = Board(picked)
    stop = threading.Event()

    pace = f"{jobs} at a time" if jobs > 1 else "one at a time"
    scope = f"{plural(len(picked), 'example')}, {pace}"
    print(f"\n{paint('Walmart PX bypass', BOLD)}  {paint(scope, DIM)}\n")
    board.draw()

    def task(example):
        run_one(example, timeout, board, stop)
        if stop_on_fail and example.code not in (None, PASS):
            stop.set()

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(task, example) for example in picked]
        while not all(future.done() for future in futures):
            board.draw()
            time.sleep(0.1)
    board.draw()
    board.clear()


def replay(picked: list, show_all: bool) -> None:
    for example in picked:
        if example.state == SKIP or not example.output:
            continue
        if not show_all and example.code == PASS:
            continue
        mark, colour = MARKS[example.code if example.code is not None else SKIP]
        print(f"\n{rule(example.name, paint(mark.strip(), colour, BOLD))}")
        print(example.output.rstrip())


def table(picked: list) -> None:
    width = max(len(e.name) for e in picked)
    for example in picked:
        state = example.code if example.code is not None else example.state
        mark, colour = MARKS[state]
        timing = f"{example.elapsed:5.1f}s" if example.code is not None else "     -"
        print(f"  {paint(mark, colour, BOLD)}  {example.name:<{width}}  {paint(timing, DIM)}  {paint(example.note or example.title, DIM)}")
        if example.outcome:
            # What Walmart actually answered, so a PASS is evidence, not a claim.
            print(detail_line(example.outcome))


def summarise(picked: list, replayed_logs: bool) -> int:
    # A heading and a tally only earn their space with more than one row.
    if len(picked) > 1:
        print(f"\n{rule('summary')}\n")
    else:
        print()
    table(picked)

    counts = {code: sum(1 for e in picked if e.code == code) for code in (PASS, FAIL, ERROR)}
    skipped = sum(1 for e in picked if e.state == SKIP)
    # A config skip never got a fair shot. A --stop-on-fail skip is not its fault.
    unconfigured = sum(1 for e in picked if e.skip_reason == "env")

    parts = [paint(f"{counts[PASS]} passed", GREEN if counts[PASS] else DIM)]
    if counts[FAIL]:
        parts.append(paint(f"{counts[FAIL]} failed", RED))
    if counts[ERROR]:
        parts.append(paint(f"{counts[ERROR]} errored", YELLOW))
    if skipped:
        parts.append(paint(f"{skipped} skipped", GREY))
    if len(picked) > 1:
        total = sum(e.elapsed for e in picked)
        wall = max((e.elapsed for e in picked), default=0)
        saved = f", {total:.0f}s of work in {wall:.0f}s" if total > wall + 1 else ""
        print(f"\n  {', '.join(parts)} of {len(picked)}{paint(saved, DIM)}")

    # Footnotes, only the ones this run actually earned.
    notes = []
    if counts[ERROR]:
        notes.append("ERR! means the run never got a fair shot: check proxies.txt and .env, not the bypass. `run.py --doctor` settles it in 10s.")
    if unconfigured:
        wanted = sorted({name for e in picked if e.skip_reason == "env" for name in e.needs
                         if not os.getenv(name)})
        notes.append(f"SKIP means unconfigured, not broken: set {', '.join(wanted)} in .env to include those flows.")
    refused = [e for e in picked if e.skip_reason == "access"]
    if refused:
        # Name the service the key actually lacks, the two are sold separately.
        services = sorted({"captcha solving (pxhc)" if "pxhc" in e.tags else
                           "the PX mobile SDK" if "mobile" in e.tags else
                           "PX web sessions" for e in refused})
        notes.append(f"{plural(len(refused), 'flow')} skipped, this key is not cleared for {', '.join(services)}. Nothing is wrong with the bypass. {contact()}")
    # Say the output exists, or a clean sweep reads like nothing happened.
    hidden = sum(1 for e in picked if e.code == PASS and e.output)
    if hidden and not replayed_logs:
        notes.append(f"{plural(hidden, 'passing example')} printed steps while running, hidden here. Rerun with --logs to read them.")
    for note in notes:
        print()
        print(wrapped(note, indent=2))
    print()

    # The worst outcome, so CI can gate on it. A skip only goes red if nothing ran.
    if counts[ERROR] or unconfigured:
        return ERROR
    if skipped and not counts[PASS] and not counts[FAIL]:
        return ERROR
    if counts[FAIL]:
        return FAIL
    return PASS


# ------ Preflight -------------------------------------------------------------


def doctor(sample: int = 5) -> int:
    import random

    from takion.common import GATEWAY_STATUS, load_proxies, mask_proxy, probe_proxy
    from takion.result import ExampleError

    print(f"\n{paint('Preflight', BOLD)}\n")
    problems = []

    # [1] Config.
    key = os.getenv("TAKION_API_KEY")
    if key:
        print(f"  {paint('ok  ', GREEN)}  TAKION_API_KEY set ({key[:10]}...{key[-4:]})")
    else:
        print(f"  {paint('FAIL', RED)}  TAKION_API_KEY missing, copy .env.example to .env")
        problems.append("api key")

    for name in ("WALMART_EMAIL", "WALMART_PASSWORD"):
        value = os.getenv(name)
        mark = paint("ok  ", GREEN) if value else paint("note", YELLOW)
        state = "set" if value else "unset, the examples needing it will be skipped"
        print(f"  {mark}  {name} {state}")

    # [1b] What captchas the key can solve. pxhc only, the init flows are unaffected.
    if key:
        access = whoami(key)
        if not access:
            print(f"  {paint('note', YELLOW)}  could not reach {WHOAMI_URL}, entitlement unknown, the run will go ahead anyway")
        elif access.get("whitelisted") is False:
            print(f"  {paint('note', YELLOW)}  not whitelisted for captcha solving, the pxhc examples will be skipped. {contact()}")
        else:
            used = access.get("requests") or {}
            plan = access.get("plan", "?")
            print(f"  {paint('ok  ', GREEN)}  pxhc: whitelisted, plan {plan}"
                  + (f", {used.get('remaining')} of {used.get('max')} requests left"
                     if used else ""))
            if expires := access.get("expires"):
                print(f"  {paint('ok  ', GREEN)}  expires {str(expires)[:19]}")
            for target in access.get("targets") or []:
                allowed = target.get("authorized") is not False
                mark = paint("ok  ", GREEN) if allowed else paint("note", YELLOW)
                site = target.get("website") or target.get("app_id")
                print(f"  {mark}  pxhc: {site} ({target.get('app_id')})"
                      + ("" if allowed else ", not cleared, pxhc there will be skipped"))

    # [2] Proxy pool.
    try:
        pool = load_proxies()
        print(f"  {paint('ok  ', GREEN)}  proxies.txt has {len(pool)} entries")
    except ExampleError as error:
        print(f"  {paint('FAIL', RED)}  {error}\n")
        return ERROR

    # [3] Ask the gateway itself, this is what catches an expired subscription.
    checked = random.sample(pool, min(sample, len(pool)))
    print(f"\n{paint(f'Proxy gateway, {len(checked)} random entries', BOLD)}\n")

    with ThreadPoolExecutor(max_workers=len(checked)) as pool_exec:
        verdicts = list(pool_exec.map(probe_proxy, checked))

    healthy = 0
    for proxy, verdict in zip(checked, verdicts):
        good = "healthy" in verdict
        healthy += good
        mark = paint("ok  ", GREEN) if good else paint("FAIL", RED)
        print(f"  {mark}  {mask_proxy(proxy)}  {paint(verdict, DIM)}")

    print(f"\n  {healthy}/{len(checked)} proxies healthy")
    if healthy == 0:
        problems.append("proxies")
        print("\n  Every proxy was refused by its own gateway, before Takion is involved.")
        print("  Verify it yourself with no code in the way:")
        first = pool[0].split(":")
        if len(first) >= 4:
            print(f"    curl -x http://USER:PASS@{first[0]}:{first[1]} http://api.ipify.org -v")
        print(f"    (402 {GATEWAY_STATUS[402]})")

    print()
    if problems:
        print(f"  {paint('Not ready', RED)}: fix {', '.join(problems)} first.\n")
        return ERROR
    print(f"  {paint('Ready', GREEN)}. A failing example now means the flow, not the setup.\n")
    return PASS


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Walmart PX examples.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("names", nargs="*", help="specific example names")
    for flag in FILTERS:
        parser.add_argument(f"--{flag}", action="store_true", help=f"only {flag} examples")
    parser.add_argument("--all", action="store_true", help="run everything (the default)")
    parser.add_argument("--list", action="store_true", help="list examples and exit")
    parser.add_argument("--doctor", action="store_true",
                        help="check .env and proxy health, then exit")
    parser.add_argument("-j", "--jobs", type=int, default=0,
                        help="how many examples to run at once (default: all of them)")
    parser.add_argument("--serial", action="store_true",
                        help="one at a time, the old behaviour")
    parser.add_argument("--logs", action="store_true",
                        help="replay every example's output, not just the failures")
    # Has to clear 3x the worst case, or a retried FAIL reads as a timeout.
    parser.add_argument("--timeout", type=int, default=1500,
                        help="per-example timeout in seconds (default 1500)")
    parser.add_argument("--stop-on-fail", action="store_true",
                        help="skip whatever has not started once one example fails")
    args = parser.parse_args()

    if args.list:
        print_list()
        return PASS

    if args.doctor:
        return doctor()

    picked = select(args)
    if not picked:
        print("No examples matched that filter. Try `python run.py --list`.")
        return ERROR

    # Settle missing env vars and pxhc clearance here, before spawning anything.
    key = os.getenv("TAKION_API_KEY") or ""
    runnable = []
    for example in picked:
        missing = example.missing_env
        refused = refusal(key, example.app_id, example.website) if key and example.app_id else ""
        if missing:
            example.state = SKIP
            example.skip_reason = "env"
            example.note = f"needs {', '.join(missing)} in .env"
        elif refused:
            example.state = SKIP
            example.skip_reason = "access"
            example.note = refused
        else:
            runnable.append(example)

    if runnable:
        jobs = 1 if args.serial else (args.jobs or len(runnable))
        execute(runnable, max(1, jobs), args.timeout, args.stop_on_fail)

    replay(picked, args.logs)
    return summarise(picked, args.logs)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(paint("\n  interrupted\n", YELLOW))
        raise SystemExit(ERROR)
