import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from takion.common import run_example
from takion.flows import run_pxhc_flow
from takion.pxhc import PxhcTarget

TARGET = PxhcTarget(
    name="pxhc-us-web",
    trigger_url="https://www.walmart.com/account/login",
    app_id="PXu6b0qd2S",
    accept_language="en-GB,en-US;q=0.9,en;q=0.8",
)


def main() -> int:
    return run_pxhc_flow(TARGET)


if __name__ == "__main__":
    raise SystemExit(run_example(main))
