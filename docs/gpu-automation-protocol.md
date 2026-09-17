# Encrypted GPU Automation Protocol

This repository provides a one-shot Kaggle GPU lane for ChatGPT automations.

## Security model

- The repository may be public.
- Plaintext task content is never committed.
- Each caller generates a fresh 32-byte symmetric session key locally.
- The task is encrypted with PyNaCl `SecretBox`.
- The session key is wrapped with the repository public key using `SealedBox`.
- The corresponding private key exists only in the private Kaggle Dataset `nazofobigpt/hermes-gpu-transport-key`.
- The GPU result is returned to GitHub Actions only as SecretBox ciphertext.
- The one-shot Kaggle kernel exits after producing the encrypted result.

## Request format

Create a unique file under `requests/gpu_tasks/<task_id>.json`:

```json
{
  "task_id": "gpu-20260918-example",
  "wrapped_key_b64": "...",
  "prompt_box_b64": "..."
}
```

Never put the plaintext prompt or the symmetric session key in GitHub.

## Caller encryption reference

Use the public key in `control/gpu_transport_public_key.b64`.

```python
import base64, json, secrets
from nacl.public import PublicKey, SealedBox
from nacl.secret import SecretBox

public_key_b64 = PUBLIC_KEY_FROM_REPO.strip()
session_key = secrets.token_bytes(SecretBox.KEY_SIZE)
prompt_box_b64 = base64.b64encode(bytes(SecretBox(session_key).encrypt(prompt.encode("utf-8")))).decode("ascii")
wrapped_key_b64 = base64.b64encode(
    SealedBox(PublicKey(base64.b64decode(public_key_b64))).encrypt(session_key)
).decode("ascii")

request = {
    "task_id": task_id,
    "wrapped_key_b64": wrapped_key_b64,
    "prompt_box_b64": prompt_box_b64,
}
```

Create the request with a unique path using the GitHub connector. The resulting commit triggers the `Encrypted GPU Task` workflow.

## Finding the result

Match the workflow run by the request commit SHA. Wait for the `Encrypted GPU Task` job to complete. Fetch the job log and extract:

```text
GPU_TASK_RESULT_B64=<ciphertext>
GPU_TASK_WORKFLOW_PASS=1
```

The ciphertext is safe to appear in the public Actions log; it cannot be read without the caller's one-time session key.

Decrypt locally:

```python
result = SecretBox(session_key).decrypt(
    base64.b64decode(result_b64)
).decode("utf-8")
```

Do not commit or log `session_key`.

## Use policy

Use this lane only when GPU/local-model computation materially helps. Normal web, Gmail, Drive, Sheets, Calendar, connector reads/writes, and short reasoning stay on the normal automation path. GPU output is advisory/computational output: the calling automation remains responsible for verification and all real-world side effects.

The current one-shot model is `llama3.1-hermes` from the persistent private model cache. Model weights are not downloaded on each task.
