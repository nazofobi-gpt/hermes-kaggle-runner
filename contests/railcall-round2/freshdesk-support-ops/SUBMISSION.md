# Submission draft

## Title
Freshdesk Support Ops — governed ticket triage and approved writes for RailCall

## Summary
A direct Freshdesk module with eight useful actions: ticket list/get/search, conversation review, create/update, note, and reply. Reads are non-mutating. Every write is explicitly airlocked through RailCall preview → human approval → execute → signed receipt. Credentials stay in the RailCall vault; egress is limited to Freshdesk; subprocess and filesystem writes are disabled.

## Gate
- [x] 8 meaningful commands
- [x] 4 read / 4 external-write split
- [x] vault-only credential access
- [x] validation + 429/error handling
- [x] deterministic unit tests
- [x] README + demo plan
- [x] current RailCall CLI flow reconciled: `railcall market publish .` is the documented sign+upload path; stale `market module sign` wording removed
- [ ] real Freshdesk API read receipt
- [ ] real human-approved write receipt
- [ ] signed receipt checked with `railcall verify <receipt>`
- [ ] marketplace publish with both contest tags
- [ ] fresh buyer install test
- [ ] marketplace listing URL
- [ ] short demo video URL
- [ ] Freelancer entry submitted by user

Do not mark `CONTEST_READY_TO_SUBMIT` until all technical items except the final Freelancer submission click are complete.
