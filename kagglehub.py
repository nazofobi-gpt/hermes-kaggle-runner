"""Compatibility shim for the Kaggle GPU control workflow.

The workflow only needs the authenticated Kaggle username to construct the
kernel slug. Returning the repository owner's known Kaggle username avoids
extra CLI/banner output being written into GITHUB_OUTPUT.
"""


def whoami():
    return {"username": "nazofobigpt"}
