import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from takion.common import run_example
from takion.flows import run_pxhc_flow
from takion.pxhc import PxhcTarget

TARGET = PxhcTarget(
    name="pxhc-identity",
    trigger_url="https://identity.walmart.com/account/login?client_id=5f3fb121-076a-45f6-9587-249f0bc160ff&redirect_uri=https%3A%2F%2Fwww.walmart.com%2Faccount%2FverifyToken&scope=openid+email+offline_access&tenant_id=elh9ie&state=%2F",
    app_id="PXu6b0qd2S",
    accept_language="en-GB,en-US;q=0.9,en;q=0.8",
)


def main() -> int:
    return run_pxhc_flow(TARGET)


if __name__ == "__main__":
    raise SystemExit(run_example(main))
