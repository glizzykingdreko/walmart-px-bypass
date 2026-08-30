# Walmart PX Bypass (US & CA, Web & Mobile)
<div align="center">
  <img src="https://img.shields.io/badge/Status-Active-brightgreen?style=flat-square" alt="Status: Active">
  <img src="https://img.shields.io/badge/Type-Reverse%20Engineering-blue?style=flat-square" alt="Type: Reverse Engineering">
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="License: MIT">
  <img src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white&style=flat-square" alt="Python">
  <a href="https://github.com/glizzykingdreko/walmart-px-bypass"><img src="https://img.shields.io/github/stars/glizzykingdreko/walmart-px-bypass?style=flat-square&logo=github" alt="GitHub stars"></a>
  <br />
</div>

![Takion x PerimeterX](assets/takion-perimeterx-x-header.png)
<div align="center">
  <a href="https://takionapi.tech/"><img src="https://takionapi.tech/badge?text=Powered+by+TakionAPI&theme=dark" alt="TakionAPI"></a>
  <br />
</div>

Example bypass implementation (add to cart, sign in and register accounts) on `walmart.com`, `walmart.ca`, `identity.walmart.com`, `advertising.walmart.com` and the Android app (`com.walmart.android`), bypass **PerimeterX** on both the web SDK and the mobile SDK as well as PXHC (Perimeter-X Hold Captcha). Antibots part is handled by [TakionAPI](https://takionapi.tech).

**IMPORTANT**

- A flagged proxy will always require a pxhc (hold captcha) to be solved, the init resolution will not be enough
- A banned proxy will never be able to correctly solve pxhc
thenfore using unbanned proxies is strictly necessary when interacting with those websites.

The current logic for triggering an HoldCaptcha block on both walamrt us, ca identity and advertising is by hammering an enpoint of requests till the session gets flagged. Something that is totally not suggested to do in production, this should serve as proof of work of a correct solving of an issued challenge.

## Table of Contents
- [Quick Start](#quick-start)
- [Important Notes](#important-notes)
- [How to Bypass PerimeterX](#how-to-bypass-perimeterx)
  - [Two Ways In](#two-ways-in)
  - [What a Block Actually Looks Like](#what-a-block-actually-looks-like)
  - [Session Consistency](#session-consistency)
  - [IP and Proxy Management](#ip-and-proxy-management)
  - [The Mobile SDK](#the-mobile-sdk)
- [Interacting with Walmart](#interacting-with-walmart)
  - [App IDs and Tenants](#app-ids-and-tenants)
  - [Headers](#headers)
  - [Add to Cart Flow](#add-to-cart-flow)
  - [Sign In Flow](#sign-in-flow)
  - [Things That Rotate](#things-that-rotate)
- [The Runner](#the-runner)
  - [Exit Codes](#exit-codes)
  - [Retries](#retries)
- [TakionAPI Solution](#takionapi-solution)
  - [Getting an API Key](#getting-an-api-key)
  - [Generating a PX Session](#generating-a-px-session)
  - [Solving a Captcha You Already Hit](#solving-a-captcha-you-already-hit)
- [FAQ](#faq)
- [Connect with me](#connect-with-me)

## Quick Start

Create a free account on the [TakionAPI Dashboard](https://takionapi.tech/trial) to start your trial and get your `TAKION_API_KEY`.

```bash
git clone https://github.com/glizzykingdreko/walmart-px-bypass.git
cd walmart-px-bypass
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, fill it in, drop your proxies into `proxies.txt` (one per line, `ip:port` or `ip:port:user:pass`), and run any single flow:

```bash
python examples/us_web_atc.py
```

Or run the whole thing in parallel:

```bash
python run.py                 # everything, all at once
python run.py --us --web      # filters combine as AND
python run.py --doctor        # is my key and proxy pool actually usable?
```

| Example | What it does | Tags |
|---|---|---|
| `us_web_atc` | Adds a product to a guest cart and reaches checkout | `us` `web` `init` |
| `us_web_signin` | Full email OTP login on identity.walmart.com | `us` `web` `init` |
| `us_mobile_signin` | Password login through the Android app's PX SDK | `us` `mobile` `init` |
| `ca_web_atc` | Same add to cart, Canadian tenant | `ca` `web` `init` |
| `ca_web_account_create` | Account registration up to phone verification | `ca` `web` `init` |
| `pxhc_us_web` | Earns a captcha on www.walmart.com and solves it | `us` `web` `pxhc` |
| `pxhc_ca_web` | Same on www.walmart.ca | `ca` `web` `pxhc` |
| `pxhc_identity` | Same on identity.walmart.com | `us` `web` `pxhc` |
| `pxhc_advertising` | Same on advertising.walmart.com | `us` `web` `pxhc` |

## Important Notes

Every flow shares one client package, [`takion/`](./takion). It keeps the PX session id, the cookie jar, the TLS fingerprint and the proxy pinned together for the whole run. This matters more than it looks: PX scores the **session**, not the single request. Solve on one proxy and fire from another, or swap the User-Agent halfway through, and you're flagged before Walmart reads your cart.

I keep this repo up to date with any changes to the flows. Always refer to it for a working example.

## How to Bypass PerimeterX

This part is general. It's about **PerimeterX** on any site that uses it, not just Walmart. If you're on a different PX target the same ideas carry over, only the app id, the endpoints and the body change.

### Two Ways In

This matters more than anything else in the repo, so let's get it out of the way first.

**px_init** (the `init` tag). You generate a clean PX session *before* the site ever looks at you funny. `generate_px_session` solves PX for a user agent and a page, and every request after that goes through that session with matching cookies, TLS fingerprint and HTTP/2 profile. This is what you want 95% of the time. It's fast and it scales.

**pxhc** (the `pxhc` tag). You already got blocked and you're staring at a captcha. You hand the `/blocked` page to the solver and it gives you back the cookies that make the origin talk to you again. Slower, reactive, but it's what saves a session you'd otherwise throw away.

Rule of thumb, build on px_init and keep pxhc as your recovery path.

### What a Block Actually Looks Like

Worth knowing precisely, because "it returned a 3xx" tells you nothing on its own. Same proxy, same URL, before and after PX flags it:

```
clean    302  location: https://www.walmart.com/redirect/identity?tp=RequestOidcCompliantIdentityTp
              body: (empty)

blocked  307  location: /blocked?url=L2FjY291bnQvbG9naW4=&uuid=aef2e879-a30b-11f1-b1c8-f895c6bebfc2
              body: blocked - redirecting
```

The `Location` header is the signal, not the status code. A `302` off `/account/login` is just the normal unauthenticated redirect. `is_blocked()` checks the header first and falls back to the status, and it also catches the third shape Walmart uses, a `200` whose JSON body carries a `/blocked` `redirectUrl`. Miss that one and a "successful" GraphQL call is actually a block.

### Session Consistency

PX doesn't grade one request in isolation, it builds a profile over the session:

- **Device consistency**, the same TLS, UA and cookie set on every request
- **Session lock**, the proxy you solved on is the proxy you send from
- **Header shape**, `sec-ch-ua` agreeing with the `user-agent`, `sec-fetch-*` matching the request type
- **Cookie continuity**, `_px3`, `_pxvid`, `_pxde` and `pxcts` travel together

Change the UA mid-session and it's flagged instantly. Consistency is the whole game.

### IP and Proxy Management

Residential or mobile, and expect an uneven pool. Some exits are refused before the solve even starts, some are too clean to ever earn a block for the pxhc examples. Both are the pool talking, not the bypass.

`fast_mode=True` is the default and it's fine for browsing. Turn it off for anything scored harder, sign up and checkout mostly, [`ca_web_account_create.py`](./examples/ca_web_account_create.py) shows this.

### The Mobile SDK

The Android app talks to the same GraphQL backend as the website but is guarded by the PX **mobile** SDK, which signs requests with `X-PX-*` headers instead of cookies:

```python
solver = TakionPxMobile(api_key, proxy)
px = solver.generate_px_headers("com.walmart.android")
```

You get the header set plus the device identity it was minted for, the user agent, the device id, the session and visitor ids. Send them together. A device id from one solve paired with an authorization from another is an easy tell.

## Interacting with Walmart

### App IDs and Tenants

Three app ids cover the whole estate, and access is granted per app id, not per host:

| App ID | Surface | Notes |
|---|---|---|
| `PXu6b0qd2S` | `www.walmart.com` | also serves `identity.walmart.com` |
| `PXnp9B16Cq` | `www.walmart.ca` | separate tenant, `qxjed8`, its own GraphQL routes |
| `PXZiTus4E5` | `advertising.walmart.com` | slower gateway, per app id solve route |

`identity.walmart.com` sharing `PXu6b0qd2S` with the storefront is the useful one. A key cleared for US storefront captchas is cleared for the login host too.

### Headers

The GraphQL XHRs share one header set. The ones that do real work:

```json
{
    "x-o-platform": "rweb",
    "x-o-platform-version": "usweb-1.300.0-...",
    "x-apollo-operation-name": "updateItems",
    "x-o-gql-query": "mutation updateItems",
    "tenant-id": "elh9ie",
    "x-o-bu": "WALMART-US"
}
```

`x-o-gql-query` and `x-apollo-operation-name` are cross-checked against the operation you're actually calling, so they can't be copy-pasted from another request. This is also why `user-agent` and `sec-ch-ua` live inline in every header block instead of a constant at the top of the file, the browser identity belongs right there in the headers you're reading.

### Add to Cart Flow

```
solve PX -> product page -> ccm bootstrap -> updateItems -> getCart -> /cart
```

The product page is the first request PX actually scores, and on CA it's also where you read the live `appVersion` and the `vtc`/`bstc` tracking ids. `updateItems` answers with the cart itself, and the items are under `lineItems`, **not** under a nested `cart` object. Read the wrong key and you'll happily report success on an empty cart. See [`us_web_atc.py`](./examples/us_web_atc.py) and [`ca_web_atc.py`](./examples/ca_web_atc.py).

### Sign In Flow

```
solve PX -> homepage chain -> GetLoginOptions -> tempo modules -> GenerateOtp -> SignInWithOTP
```

The tempo modules are the CMS calls the SPA fires between screens. Skipping them is a tell, a real browser always loads them. The example submits a **random** six digit code on purpose, reading the real one needs a mailbox and it isn't what this proves. Walmart answering the wrong code with an OTP error means the flow reached it and PX never got in the way, and that's the pass. A `RATE_LIMIT_EXCEEDED` is also a pass, you only get rate limited by a backend that trusts you enough to rate limit you.

### Things That Rotate

Two categories, and only one of them is your problem:

**Read live.** `x-o-platform-version` comes off the page on every run (`find_platform_version`), so a frontend release doesn't break anything. Walmart shipped `usweb-1.282` to `usweb-1.300` while this repo was being written and nothing needed touching.

**Pinned.** The persisted query hashes at the top of each example. When one starts answering `PersistedQueryNotFound`, re-pull it from a browser session. They're all named `H_*` so they're easy to find.

## The Runner

Every example is standalone, but `run.py` runs the selected ones **in parallel**, so a full sweep costs about as long as its slowest flow instead of the sum of all nine. A running row shows the step it's on, not just how long it's been sitting there, so a slow flow and a stuck flow don't look the same:

```
Walmart PX bypass  9 examples, 9 at a time

  PASS  us_web_atc              30.0s  US web, add to cart
  PASS  ca_web_atc              14.8s  CA web, add to cart
  ⠹     pxhc_us_web             62.3s  Solving...
  SKIP  us_mobile_signin            -  needs WALMART_PASSWORD in .env
```

Those rows get wiped when the run ends, so the summary is the only table left. Every flow closes by printing the response its verdict rests on, so a `PASS` carries its evidence instead of asking you to take its word for it:

```
── summary ─────────────────────────────────────────────────────────────────────

  PASS  us_mobile_signin   17.2s  US mobile, sign in (password)
        └ SignInV2 200  {"data":{"signInV2":{"canUseEmailOTP":false,"errors":[{"…
  PASS  pxhc_ca_web        45.9s  pxhc, www.walmart.ca
        └ replay www.walmart.ca/en/ip/-/619MIY9EDZLW 200  340247 bytes of HTML, title 'Pokemon …

  2 passed of 2, 63s of work in 46s
```

JSON gets quoted directly. A 400KB HTML page gets described instead, size and `<title>`, which is what tells you Walmart served the real page and not an interstitial.

| Flag | What it does |
|---|---|
| `--jobs N` | cap the concurrency, default is all of them at once |
| `--serial` | one at a time |
| `--logs` | replay every flow's output, not just the failures |
| `--stop-on-fail` | skip whatever hasn't started once one fails |
| `--timeout` | per-example cap in seconds, default 1500 |

### Exit Codes

| Code | Meaning | What to do |
|---|---|---|
| `0` | PASS, the flow reached its goal | Nothing |
| `1` | FAIL, you reached Walmart but the flow didn't succeed | Read the flow, a hash may have rotated |
| `2` | ERROR, the run never got a fair shot | Check `proxies.txt` and `.env`, not the bypass |

The 1 vs 2 split is the whole point. A dead proxy, a rejected key or a missing env var is a `2` and tells you nothing about whether the bypass works. Only a `1` is worth debugging.

### Retries

Anything short of a pass gets the flow re-run from the top on a fresh proxy, three times, before the verdict stands. That covers a PX block, an exit dying mid-request, and a flow that just didn't reach its goal, all of which a residential pool serves up on its own now and then.

So a `FAIL` on the board means three separate exits couldn't do it. That one's worth reading. The trade is that a genuinely broken flow takes three runs to say so.

## TakionAPI Solution

![TakionAPI](assets/perimeterx.png)

Unless you want to start deobfuscating the PX sensor, understanding it, and, the annoying part, keeping it up to date every time it changes, we at [TakionAPI](https://takionapi.tech) already do that for you. Same for the TLS client, which goes stale the moment Chrome ships a new hello. You focus on your business logic, we handle the bypass.

[`takion/`](./takion) is the whole client, ready to drop in.

- [TakionAPI Docs](https://docs.takionapi.tech)
- [TakionAPI Trial](https://dashboard.takionapi.tech)
- [TakionAPI Discord](https://takionapi.tech/discord) for custom development and support.

### Getting an API Key

Start with a free trial at [takionapi.tech](https://takionapi.tech/demo) to get a key with some tokens in it. Nothing more than an email required, run your tests and reach out for anything.

Three services, cleared separately on the same key:

| Service | Used by | How you find out |
|---|---|---|
| px-web | the `init` web flows | the first `/generate` call answers with a Discord pointer |
| px-mobile | `us_mobile_signin` | same, its own message |
| pxhc | the `pxhc_*` flows | `/whoami`, up front, per app id |

Only pxhc can be checked before you spend anything:

```bash
curl -H "x-api-key: YOUR_KEY" https://pxhc.takionapi.tech/whoami
```

`python run.py --doctor` prints that with your proxy health next to it. px-web and px-mobile have no equivalent, so a trial that doesn't cover them only says so when a flow calls them. Either way you get a `SKIP` and the Discord link, not a stack trace:

```
  SKIP  us_web_atc          -  Please contact us on discord for extending your tiral to px-web ...
  SKIP  us_mobile_signin    -  In order to extend your trial for perimeter x mobile, ...
  SKIP  pxhc_us_web         -  This key is not whitelisted for captcha solving ...

  0 passed, 9 skipped of 9

  9 flows skipped, this key is not cleared for PX web sessions, captcha solving (pxhc), the PX
  mobile SDK. Nothing is wrong with the bypass. Ask for access on Discord ...
```

A skip doesn't turn the run red on its own, a sweep that ran everything your key covers did its job. A sweep where **nothing** ran exits `2`, because that one didn't.

### Generating a PX Session

Three classes, one import:

```python
from takion import TakionPxWeb, TakionPxMobile, TakionPxHC
```

Solve once, then use it like `requests`:

```python
solver = TakionPxWeb(api_key, proxy)
solver.generate_px_session(
    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    app_id="PXu6b0qd2S",
    page_url="https://www.walmart.com/",
)

page = solver.get("https://www.walmart.com/cart", headers)
response = solver.post(url, headers, data=body)
```

### Solving a Captcha You Already Hit

The four Walmart surfaces differ only in which URL earns the block, which app id serves it and how the solve endpoint is addressed, so they're `PxhcTarget` rows instead of four copies of the same file:

```python
from takion import PxhcTarget
from takion.flows import run_pxhc_flow

TARGET = PxhcTarget(
    name="pxhc-us-web",
    trigger_url="https://www.walmart.com/account/login",
    app_id="PXu6b0qd2S",
)
run_pxhc_flow(TARGET)
```

One thing to watch. A solve can come back `verdict=rejected` with `solve_status=-1` and **still hand you a `_px3`**. That cookie is a dud, the origin bounces it straight back to `/blocked`. The flow re-submits up to three times on a rejection, then replays anyway and lets the origin have the last word.

## FAQ

> A `pxhc` example says "no block after 60 requests".

Your proxy is too clean to get flagged. That's a compliment to your pool and a problem for this specific test :P use a dirtier one.

> Everything comes back `SKIP`.

Your key isn't cleared for the service those flows need, and the summary names which one. px-web covers the `init` web flows, px-mobile covers `us_mobile_signin`, pxhc covers the captcha ones, and they're cleared separately. Nothing wrong with the bypass, and rotating proxies all day won't change it. Run `--doctor`, then ask on [Discord](https://takionapi.tech/discord) or at [hello@takionapi.tech](mailto:hello@takionapi.tech) for whitelisting your key. We require this extra steps in order to prevent fraudolent actions.

> The solve keeps coming back rejected.

`verdict=rejected` with `solve_status=-1` is the solver refusing its own work, and the `_px3` it returns with it won't be accepted. The flow already re-solves three times. If every one is rejected on a surface, that's ours to fix, hit us on Discord.

> A `200` came back but nothing worked.

Check for a `/blocked` `redirectUrl` in the body. Walmart's GraphQL layer answers a flagged session with a `200` that hides a block. `is_blocked()` catches it.

> I'm on a different PX-protected site, do you support it?

Change the `app_id` and the `page_url` and you're most of the way there. Not sure about your target's flow? Hit us on [Discord](https://takionapi.tech/discord).

## Connect with me

If you found this project helpful or interesting, consider starring the repo and following me for more security research and tools, or buy me a coffee to keep me up

<p align="center">
  <a href="https://github.com/GlizzyKingDreko"><img src="https://img.shields.io/badge/GitHub-100000?style=for-the-badge&logo=github&logoColor=white" alt="GitHub"></a>
  <a href="https://twitter.com/GlizzyKingDreko"><img src="https://img.shields.io/badge/Twitter-1DA1F2?style=for-the-badge&logo=twitter&logoColor=white" alt="Twitter"></a>
  <a href="https://medium.com/@GlizzyKingDreko"><img src="https://img.shields.io/badge/Medium-12100E?style=for-the-badge&logo=medium&logoColor=white" alt="Medium"></a>
  <a href="https://discord.com/users/GlizzyKingDreko"><img src="https://img.shields.io/badge/Discord-7289DA?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="mailto:glizzykingdreko@protonmail.com"><img src="https://img.shields.io/badge/ProtonMail-8B89CC?style=for-the-badge&logo=protonmail&logoColor=white" alt="Email"></a>
  <a href="https://buymeacoffee.com/glizzykingdreko"><img src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-yellow?style=for-the-badge&logo=buy-me-a-coffee&logoColor=white" alt="Buy Me a Coffee"></a>
</p>
