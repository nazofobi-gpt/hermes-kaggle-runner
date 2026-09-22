"""Synthetic G-080 coding fixture: deterministic job-config validation.

Original project code for public-safe evaluation; standard-library only.
"""
from __future__ import annotations

_ALLOWED = {"project_id", "timeout_s", "retries", "tags"}

def normalize_job_config(raw: dict) -> dict:
    """Validate and normalize a small automation-job config without guessing."""
    if not isinstance(raw, dict):
        raise TypeError("config must be a dict")
    unknown = set(raw) - _ALLOWED
    if unknown:
        raise ValueError(f"unknown keys: {sorted(unknown)}")
    project_id = raw.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id is required")
    timeout = raw.get("timeout_s", 30)
    retries = raw.get("retries", 2)
    if not isinstance(timeout, int) or not 1 <= timeout <= 300:
        raise ValueError("timeout_s must be integer 1..300")
    if not isinstance(retries, int) or not 0 <= retries <= 5:
        raise ValueError("retries must be integer 0..5")
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(x, str) for x in tags):
        raise ValueError("tags must be a list of strings")
    norm_tags = sorted({x.strip().lower() for x in tags if x.strip()})
    return {
        "project_id": project_id.strip(),
        "timeout_s": timeout,
        "retries": retries,
        "tags": norm_tags,
    }
