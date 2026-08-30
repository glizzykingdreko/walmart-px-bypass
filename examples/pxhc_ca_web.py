import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from takion.common import run_example
from takion.flows import run_pxhc_flow
from takion.pxhc import PxhcTarget

TARGET = PxhcTarget(
    name="pxhc-ca-web",
    trigger_url="https://www.walmart.ca/en/ip/-/619MIY9EDZLW",
    app_id="PXnp9B16Cq",
    accept_language="en-CA,en;q=0.9",
)


def main() -> int:
    return run_pxhc_flow(TARGET)


if __name__ == "__main__":
    raise SystemExit(run_example(main))
