import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from takion.common import run_example
from takion.flows import run_pxhc_flow
from takion.pxhc import PxhcTarget

TARGET = PxhcTarget(
    name="pxhc-advertising",
    trigger_url="https://advertising.walmart.com/signin?adtechClientId=d8e4dc23-caef-4401-9e36-fa89422644a2&rd=https%3A%2F%2Fadvertising.walmart.com%2Fadtech",
    app_id="PXZiTus4E5",
    accept_language="en-GB,en-US;q=0.9,en;q=0.8",
    # This gateway is slower than the others, a 30s read times out mid-hammer.
    timeout=45,
    # Advertising solves are addressed per app id, POST /{app_id}/solve.
    app_id_in_path=True,
)


def main() -> int:
    return run_pxhc_flow(TARGET)


if __name__ == "__main__":
    raise SystemExit(run_example(main))
