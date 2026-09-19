# SKILL-028 paired structural eval

This is a frozen **structural routing/guardrail ablation**, not a model-quality or operator-time claim.

Baseline is the canonical lifecycle baseline: local/manual-first with no dedicated free-first routing/fallback runbook. Candidate implements the routing constraints already documented in SKILL-028 1.3.

Twelve deterministic cases cover batch, browser, scheduled/serverless, bounded GPU, marketplace-account action, private client data, strict-zero always-on, Kaggle server-farming negative, Quick Tunnel production negative, provider exhaustion/fallback, local-simple work, and paid-without-approval.

Promotion remains blocked until a same-environment live paired run measures real operator minutes/task execution across representative work. This fixture only measures deterministic route/safety decision coverage.
