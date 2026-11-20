import json
import os
import re
import secrets
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from takion import TakionPxWeb
from takion.common import (
    ROOT, api_key, detail, find_platform_version, json_body, outcome,
    raise_if_blocked, run_example, solve_with_retry, step,
)
from takion.result import FAIL, PASS

APP_ID = "PXnp9B16Cq"
TENANT_ID = "qxjed8"
FALLBACK_PLATFORM = "caweb-1.173.1-c25ee44a95e7802fdc2073b775d1044335bb50e0-8311154r"

PRODUCT_URL = "https://www.walmart.ca/en/ip/-/619MIY9EDZLW"
US_ITEM_ID = "619MIY9EDZLW"
OFFER_ID = "6509AA77019C38A3A58416DEE6A7D493"
CATALOG_SELLER_ID = "102909707"
PREFERRED_STORE_ID = 1061
PRICE = 374.99
PRODUCT_NAME = "Pokemon Prismatic Evolutions Super-Premium Collection"

# Persisted-query hashes, rotate with Walmart's frontend.
H_MERGE_CART = "ab341b8f69860284b8e2457f7c793a4f41fd57c7432ac2cef9513d639ea73650"
H_UPDATE_ITEMS = "45fca98d0f0fb2ffc2ccf8a3290b89141cdad6c9096c3fe39303e2fdf8f524b1"
H_PAC_PAGE = "1b2a0216f2915678802dee3cac7f5431497a6a7e56f226b610aa90f5779f22f2"

PAYLOADS = os.path.join(ROOT, "examples", "payloads")


def load_payload(name: str) -> dict:
    return json.loads(open(os.path.join(PAYLOADS, name)).read())


def traceparent() -> str:
    return f"00-{secrets.randbits(128):032x}-{secrets.randbits(64):016x}-00"


def gql_headers(op: str, kind: str, platform_version: str, *, is_post: bool) -> dict:
    tp = traceparent()
    cid = secrets.token_urlsafe(27)[:36]
    headers = {
        "x-o-mart": "B2C",
        "x-o-gql-query": f"{kind} {op}",
        "sec-ch-ua-platform": '"macOS"',
        "x-o-segment": "oaoh",
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "x-enable-server-timing": "1",
        "sec-ch-ua-mobile": "?0",
        "baggage": f"trafficType=customer,deviceType=desktop,renderScope=SSR,webRequestSource=Browser,pageName=itemPage,requestTs={int(time.time() * 1000)},tpid={tp}",
        "x-latency-trace": "1",
        "traceparent": tp,
        "wm_mp": "true",
        "accept": "application/json",
        "content-type": "application/json",
        "x-apollo-operation-name": op,
        "tenant-id": TENANT_ID,
        "downlink": "10",
        "wm_qos.correlation_id": cid,
        "x-o-platform": "rweb",
        "x-o-platform-version": platform_version,
        "accept-language": "en-CA",
        "x-o-ccm": "server",
        "x-o-bu": "WALMART-CA",
        "dpr": "2",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "wm_page_url": PRODUCT_URL,
        "x-o-correlation-id": cid,
    }
    if is_post:
        headers["origin"] = "https://www.walmart.ca"
    headers.update({
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": PRODUCT_URL,
        "accept-encoding": "gzip, deflate, br, zstd",
        "priority": "u=1, i",
    })
    return headers


def update_items_body() -> dict:
    body = load_payload("ca_update_items.json")
    item = body["input"]["items"][0]
    item["offerId"] = OFFER_ID
    item["usItemId"] = US_ITEM_ID
    item["lineItemId"] = f"PRD{US_ITEM_ID}"
    item["name"] = PRODUCT_NAME
    return body


def pac_variables(vtc: str, bstc: str) -> dict:
    return {
        "p13n": {
            "promoOffer": "",
            "catalogSellerId": CATALOG_SELLER_ID,
            "pageId": US_ITEM_ID,
            "offerId": OFFER_ID,
            "userReqInfo": {
                "preferredStoreId": PREFERRED_STORE_ID,
                "vtc": vtc,
                "bstc": bstc,
                "featureAvailable": {"hs": False, "cp": False, "acc": False},
                "featureSelected": {"hs": False, "cp": False, "acc": False},
                "cartContext": {
                    "items": [{
                        "id": US_ITEM_ID,
                        "price": PRICE,
                        "qty": 1,
                        "fulfillmentIntent": "SHIPPING",
                        "fulfillmentGroup": "FCGroup",
                        "conditionCode": None,
                        "conditionGroupCode": None,
                    }],
                    "cartIntent": "SHIPPING",
                    "enableMultipleProtectionPlan": False,
                },
                "refererContext": {"source": ""},
            },
            "userClientInfo": {"deviceType": "desktop", "callType": "CLIENT"},
        },
        "pageType": "PostAddtoCartPage",
        "tenant": "CA_GLASS",
        "enableUnifiedBadges": True,
        "enableSocialProofBadges": False,
        "enableStreamlinedBadges": False,
        "enableAOSModuleAttribute": True,
        "enableSoftBundleOnPAC": False,
        "enableOneCreditOnboarding": False,
        "enablePromotionMessages": False,
        "enableSpecialCtaContext": False,
        "enableItemLimits": False,
        "isBulkUpSaveEnabled": False,
        "enableFastBadgingV2": False,
        "enableLocalFindsPAC": False,
        "enableVolumePricing": False,
    }


def main() -> int:
    key = api_key()

    # [1] Solve PX, rotating proxies if the pool hands us a bad exit.
    step(1, "Solving PX (Walmart CA)...")
    solver, px, _ = solve_with_retry(
        lambda proxy: TakionPxWeb(key, proxy),
        lambda client: client.generate_px_session(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
            app_id=APP_ID,
            page_url=PRODUCT_URL,
        ),
    )
    detail(f"px cookies: {[k for k in px if k != 'extra']}")
    detail(f"session -> {solver.session_id}\n")

    # [2] Product page, also the source of the live platform version and vtc/bstc.
    step(2, "GET product page...")
    product_page = solver.get(PRODUCT_URL, {
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "sec-fetch-site": "none",
        "sec-fetch-mode": "navigate",
        "sec-fetch-user": "?1",
        "sec-fetch-dest": "document",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "en-CA",
        "priority": "u=0, i",
    })
    html = product_page.text or ""
    raise_if_blocked(product_page, "product page")

    platform_version = find_platform_version(html, "caweb-", FALLBACK_PLATFORM)
    vtc_match = re.search(r'"vtc"\s*:\s*"([^"]+)"', html)
    bstc_match = re.search(r'"bstc"\s*:\s*"([^"]+)"', html)
    vtc = vtc_match.group(1) if vtc_match else ""
    bstc = bstc_match.group(1) if bstc_match else vtc
    detail(
        f"status={product_page.status_code} bytes={len(html)} platform={platform_version[:22]}... vtc={'y' if vtc else 'n'}\n"
    )

    # [3] Bootstrap config.
    step(3, "GET ccm bootstrap...")
    bootstrap = solver.get(
        "https://www.walmart.ca/orchestra/api/ccm/v3/bootstrap?configNames=account,ads,amends,auto_care_center,bookslot,brandpage,cart,category,checkout,converse,footer,gcomm,header,help,homepage,identity,list,marketplace,nonprofits,partnerships,pickuptoday,pricing,promotions,recommendations,search,serviceability,settings,sharedpreferences,sitemap,slotmanagement,staging,subscription,suggestions,topdeals",
        gql_headers("bootstrap", "query", platform_version, is_post=False),
    )
    detail(f"status={bootstrap.status_code}\n")

    # [4] MergeAndGetCart, establishes the cart this session owns.
    step(4, "POST MergeAndGetCart...")
    merge = solver.send_request(
        "POST",
        f"https://www.walmart.ca/orchestra/graphql/MergeAndGetCart/{H_MERGE_CART}",
        gql_headers("MergeAndGetCart", "mutation", platform_version, is_post=True),
        data=json.dumps({"variables": load_payload("ca_merge_cart.json")}, separators=(",", ":")),
    )
    raise_if_blocked(merge, "MergeAndGetCart")
    detail(f"status={merge.status_code} {json.dumps(json_body(merge))[:120]}\n")

    # [5] updateItems, the actual add to cart.
    step(5, "POST updateItems (add to cart)...")
    update = solver.send_request(
        "POST",
        f"https://www.walmart.ca/orchestra/graphql/updateItems/{H_UPDATE_ITEMS}",
        gql_headers("updateItems", "mutation", platform_version, is_post=True),
        data=json.dumps({"variables": update_items_body()}, separators=(",", ":")),
    )
    raise_if_blocked(update, "updateItems")

    update_data = json_body(update)
    # The mutation answers with the cart itself, items live under `lineItems`.
    cart = (update_data.get("data") or {}).get("updateItems") or {}
    items_in_cart = len(cart.get("lineItems") or []) if isinstance(cart, dict) else 0
    errors = update_data.get("errors")
    detail(
        f"status={update.status_code} errors={bool(errors)} cartId={cart.get('id')} items_in_cart={items_in_cart}"
    )
    if errors or not items_in_cart:
        detail(f"body: {json.dumps(update_data)[:220]}")
        outcome(update, "updateItems")
        return FAIL
    # The verdict rests on this call, not on the trailing PACPage.
    outcome(update, "updateItems")
    print()

    # [6] PACPage, the post-add-to-cart page a real browser loads next.
    step(6, "GET PACPage...")
    pac = solver.get(
        f"https://www.walmart.ca/orchestra/graphql/PACPage/{H_PAC_PAGE}",
        gql_headers("PACPage", "query", platform_version, is_post=False),
        params={"variables": json.dumps(pac_variables(vtc, bstc), separators=(",", ":"))},
    )
    detail(f"status={pac.status_code} {json.dumps(json_body(pac))[:120]}")
    return PASS


if __name__ == "__main__":
    raise SystemExit(run_example(main))
