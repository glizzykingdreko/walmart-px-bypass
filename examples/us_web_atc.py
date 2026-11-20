import json
import os
import sys
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from takion import TakionPxWeb
from takion.common import (
    ROOT, api_key, detail, json_body, outcome, raise_if_blocked,
    run_example, solve_with_retry, step,
)
from takion.result import FAIL, PASS

APP_ID = "PXu6b0qd2S"
PLATFORM_VERSION = "usweb-1.327.6-09c9b600c16cbc6083e40664a1fb71343429742f-N71544r"

# Persisted-query hashes, re-pull these on a PersistedQueryNotFound.
H_UPDATE_ITEMS = "b30082a02ec068e0351926fabd248b52f51b18e4d66d3205900ad3959fee6360"
H_GET_CART = "053d0c921c278a58cdf9c0df84fd0afff3ed2f7942e0c5212092dcdadce7ba62"

PRODUCT = {
    "usItemId": "5687290684",
    "offerId": "E5FEBCF68B8C393299A2A7EE43D9B5B7",
    "name": "Avène Mineral Sunscreen Multi-Defense Fluid SPF 50+, Face Sunscreen 1.3 fl oz",
    "page_path": "/ip/Avene-Mineral-Sunscreen-Multi-Defense-Fluid-SPF-50/5687290684",
    "quantity": 1,
}
PAGE_URL = f"https://www.walmart.com{PRODUCT['page_path']}"

FEATURES = [
    "lmpdel", "mlrx", "vsrx", "maappl", "accfournudge", "potp", "byod", "vptires",
    "pdr", "gepmss", "dd", "qsr", "qsr_qty", "cbs", "tfd", "wfss",
]

# ~135 feature flags, kept in a JSON file so this stays readable.
PAYLOAD_FILE = os.path.join(ROOT, "examples", "payloads", "us_update_items.json")

NAV_HEADERS = {
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "sec-fetch-site": "none",
    "sec-fetch-mode": "navigate",
    "sec-fetch-user": "?1",
    "sec-fetch-dest": "document",
    "sec-ch-ua": '"Not-A.Brand";v="99", "Google Chrome";v="157", "Chromium";v="157"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "accept-language": "en-US",
}


def gql_headers(op: str, kind: str) -> dict:
    return {
        "x-o-mart": "B2C",
        "x-o-gql-query": f"{kind} {op}",
        "sec-ch-ua-platform": '"macOS"',
        "x-o-segment": "oaoh",
        "sec-ch-ua": '"Not-A.Brand";v="99", "Google Chrome";v="157", "Chromium";v="157"',
        "x-enable-server-timing": "1",
        "sec-ch-ua-mobile": "?0",
        "wm_mp": "true",
        "accept": "application/json",
        "content-type": "application/json",
        "x-apollo-operation-name": op,
        "tenant-id": "elh9ie",
        "x-o-platform": "rweb",
        "x-o-platform-version": PLATFORM_VERSION,
        "accept-language": "en-US",
        "x-o-ccm": "server",
        "x-o-bu": "WALMART-US",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
        "wm_page_url": PAGE_URL,
        "origin": "https://www.walmart.com",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": PAGE_URL,
        "accept-encoding": "gzip, deflate, br, zstd",
        "priority": "u=1, i",
    }


def build_update_items_body() -> str:
    body = json.loads(open(PAYLOAD_FILE).read())
    item = body["variables"]["input"]["items"][0]
    item["usItemId"] = PRODUCT["usItemId"]
    item["offerId"] = PRODUCT["offerId"]
    item["name"] = PRODUCT["name"]
    item["quantity"] = PRODUCT["quantity"]
    body["variables"]["input"]["cartId"] = ""
    return json.dumps(body, separators=(",", ":"))


def main() -> int:
    key = api_key()

    # [1] Solve PX, rotating proxies if the pool hands us a bad exit.
    step(1, "Solving PX (Walmart US)...")
    solver, px, _ = solve_with_retry(
        lambda proxy: TakionPxWeb(key, proxy),
        lambda client: client.generate_px_session(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
            app_id=APP_ID,
            page_url=PAGE_URL,
        ),
    )
    detail(f"px cookies: {[k for k in px if k != 'extra']}")
    detail(f"session -> {solver.session_id}\n")

    # [2] Product page, the first request PX actually scores.
    step(2, "GET product page...")
    page = solver.get(PAGE_URL, NAV_HEADERS)
    raise_if_blocked(page, "product page")
    detail(f"status={page.status_code} (PX cleared)\n")

    solver.get(
        "https://www.walmart.com/orchestra/api/ccm/v3/bootstrap?configNames=account,shared,cart",
        {
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
            "accept": "application/json",
            "x-o-platform": "rweb",
            "x-o-bu": "WALMART-US",
            "tenant-id": "elh9ie",
            "sec-fetch-site": "same-origin",
            "referer": PAGE_URL,
            "accept-language": "en-US",
        },
    )

    # [3] Add to cart.
    step(3, "POST updateItems (add to cart)...")
    upd = solver.post(
        f"https://www.walmart.com/orchestra/home/graphql/updateItems/{H_UPDATE_ITEMS}",
        gql_headers("updateItems", "mutation"),
        data=build_update_items_body(),
    )
    raise_if_blocked(upd, "updateItems")

    cart = (json_body(upd).get("data") or {}).get("updateItems") or {}
    cart_id = cart.get("id")
    line_items = cart.get("lineItems") or []
    qty = line_items[0].get("quantity") if line_items else None
    is_guest = (cart.get("customer") or {}).get("isGuest")
    detail(f"status={upd.status_code} cartId={cart_id} qty={qty} guest={is_guest}")
    if not (cart_id and qty):
        detail(f"unexpected updateItems body: {(upd.text or '')[:200]}")
        outcome(upd, "updateItems")
        return FAIL
    print()

    # [4] Read the cart back, confirms the item persisted server-side.
    step(4, "GET getCart...")
    gc_vars = json.dumps(
        {
            "cartInput": {
                "cartId": cart_id,
                "enableLiquorBox": True,
                "enableCartSplitClarity": False,
                "features": FEATURES,
            },
        },
        separators=(",", ":"),
    )
    gc = solver.get(
        f"https://www.walmart.com/orchestra/home/graphql/getCart/{H_GET_CART}?variables={quote(gc_vars)}",
        gql_headers("getCart", "query"),
    )
    gc_cart = (json_body(gc).get("data") or {}).get("cart") or {}
    detail(
        f"status={gc.status_code} cart.id={gc_cart.get('id')} checkoutable={gc_cart.get('checkoutable')}\n"
    )

    # [5] Proceed to checkout.
    step(5, "GET /cart...")
    cart_page = solver.get(
        "https://www.walmart.com/cart",
        {**NAV_HEADERS, "sec-fetch-site": "same-origin", "referer": PAGE_URL},
    )
    raise_if_blocked(cart_page, "/cart")
    detail(f"status={cart_page.status_code}, checkout entry reached")
    outcome(cart_page, "/cart")
    return PASS


if __name__ == "__main__":
    raise SystemExit(run_example(main))
