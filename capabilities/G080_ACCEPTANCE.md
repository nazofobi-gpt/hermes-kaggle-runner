# G-080 capability acceptance bundle — 2026-10-05

This public-safe bundle strengthens existing Candidate skills; it does not create duplicate skill IDs.

- SKILL-040 1.1: paginated JSON API/data extraction with bounded retry, schema rejection, deduplication, loop/max-page guards, CSV output, and environment-only bearer auth.
- SKILL-043 1.1: responsive HTML/CSS/JS landing + admin surface with deterministic accessibility/responsiveness/dependency/network gate.

Demand basis: current Freelancer API/Python automation work asks for REST integration, JSON validation/transformation, retries/error handling/logging, and data extraction; current frontend work continues to require responsive small web surfaces.

Public boundary: generic/sanitized fixtures only. No customer data, credentials, NDA/IP material, marketplace bid/send/spend, account mutation, production deployment, or third-party runtime dependency. public_safety_verify.py fails closed on common secret signatures and non-stdlib Python imports. Source in this bundle was authored for the fixture; no third-party code is copied or vendored.

Verification:
1. python capabilities/public_safety_verify.py
2. python capabilities/api_pagination_etl.py selftest
3. python capabilities/api_pagination_etl.py fixture --input capabilities/api_fixture.json --output /tmp/g080.csv
4. python capabilities/api_pagination_etl.py benchmark
5. python capabilities/frontend_verify.py selftest
6. python capabilities/frontend_verify.py verify
7. python capabilities/frontend_verify.py benchmark
