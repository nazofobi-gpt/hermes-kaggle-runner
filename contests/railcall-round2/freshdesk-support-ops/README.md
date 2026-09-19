# Freshdesk Support Ops for RailCall

Direct Freshdesk support operations with eight governed actions.

**Read-only:** list tickets, get ticket, search tickets, list conversations.

**Writes:** create ticket, update ticket, add note, reply. Each write declares `side_effects: external`, so RailCall stages preview → human approval → execute → signed receipt.

## Configure

Configure the module's `freshdesk` credential in Studio Integrations with `api_key` and a Freshdesk subdomain such as `acme`. The handler reads credentials only through `__rc_helpers__["vault_get"]`; it never reads environment variables or vault files.

Sandbox: network only to `*.freshdesk.com`; subprocess disabled; filesystem writes disabled.

## Local QA

Run:

```bash
python3 -m unittest discover -s tests -v
railcall version
railcall market whoami
```

The deterministic unit suite validates the eight-command manifest, read/write airlock split, credential isolation, bounded inputs, Freshdesk Basic Auth construction, 429 handling, and handler-to-command wiring.

## Current RailCall publish flow

The current RailCall CLI documents `railcall market publish .` as the marketplace command that signs and uploads the module. Do not rely on the older `railcall market module sign` wording: that command is not present in the current CLI reference.

Publishing is intentionally **not** performed until the live verification gates below pass and the connected publisher account is authorized for the contest entry.

## Live verification gate

Before marking the package ready:

1. Configure an authorized Freshdesk test account/API key in RailCall Integrations.
2. Execute at least one real read action and retain its RailCall receipt.
3. Stage at least one external write (recommended: `freshdesk.add_note`), inspect the Sends payload, explicitly approve it, and verify the resulting Freshdesk change.
4. Verify the signed receipt with `railcall verify <receipt>` and confirm secrets are redacted.
5. Run `railcall market publish .` only after the real-API gates pass and publisher identity is confirmed.
6. Fresh-install the published marketplace build and repeat one real read plus one approved write.

## Failure behavior

Positive ids only; `per_page <= 100`; arbitrary domains are rejected. HTTP 429 surfaces `Retry-After`; other HTTP/network failures are bounded. The API key is never returned.

## Limits

Unit tests use a fake HTTP transport. Contest completion still requires a real Freshdesk test account/API key, real RailCall receipts, marketplace publishing, and a fresh-install buyer test. Freshdesk does not expose a general idempotency-key contract for these endpoints, so the module does not claim provider-idempotent writes.

Listing tags: `contest:round2` and `contest:2026Q3`.
