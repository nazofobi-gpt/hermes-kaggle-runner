# Freshdesk Support Ops for RailCall

Direct Freshdesk support operations with eight governed actions.

**Read-only:** list tickets, get ticket, search tickets, list conversations.

**Writes:** create ticket, update ticket, add note, reply. Each write declares `side_effects: external`, so RailCall stages preview → human approval → execute → signed receipt.

## Configure

Configure the module's `freshdesk` credential in Studio Integrations with `api_key` and a Freshdesk subdomain such as `acme`. The handler reads credentials only through `__rc_helpers__["vault_get"]`; it never reads environment variables or vault files.

Sandbox: network only to `*.freshdesk.com`; subprocess disabled; filesystem writes disabled.

## Verify

Run `python3 -m unittest discover -s tests -v`. Then sign and verify with RailCall, load in Studio, and exercise each command. For a write demo, stage `freshdesk.add_note`, inspect the exact ticket/body in Sends, approve, and verify both Freshdesk and the signed receipt.

## Failure behavior

Positive ids only; `per_page <= 100`; arbitrary domains are rejected. HTTP 429 surfaces `Retry-After`; other HTTP/network failures are bounded. The API key is never returned.

## Limits

Unit tests use a fake HTTP transport. Contest completion still requires a real Freshdesk test account/API key, RailCall sign/verify, fresh-install Studio run, real API read receipt, and approved write receipt. Freshdesk does not expose a general idempotency-key contract for these endpoints, so the module does not claim provider-idempotent writes.

Listing tags: `contest:round2` and `contest:2026Q3`.
