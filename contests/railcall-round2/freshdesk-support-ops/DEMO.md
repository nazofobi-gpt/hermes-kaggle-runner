# Demo plan

1. Show the module loaded in Studio and its sandbox capabilities.
2. Show Freshdesk credential configured in Integrations without exposing the key.
3. Run list/get/search/conversations reads and inspect receipts.
4. Stage add_note; pause at Sends to show the exact approval payload.
5. Approve; show the Freshdesk note and signed RailCall receipt.
6. Stage an update_ticket status/priority mutation; approve and verify.
7. Trigger one validation failure and show fail-closed behavior.
8. Fresh-install the marketplace build and repeat one read + one approved write.
