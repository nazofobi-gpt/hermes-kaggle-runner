# hermes-kaggle-runner

Public GitHub Actions runner for controlled remote shell tasks and authenticated calls to an ephemeral Kaggle GPU model endpoint.

## Required repository secrets

Create these under **Settings → Secrets and variables → Actions → New repository secret**:

- `KAGGLE_BASE_URL` — the current Cloudflare/OpenAI-compatible base URL ending in `/v1`.
- `KAGGLE_API_KEY` — the current Bearer token generated inside the Kaggle notebook.

Never commit either value to this repository.

## Workflows

- **Remote Terminal** runs `commands/run.sh` on a fresh Ubuntu GitHub-hosted runner. It does not receive Kaggle secrets.
- **Kaggle Model Call** sends `requests/prompt.txt` to the configured Kaggle endpoint with model `llama3.1-hermes`.

The Kaggle Quick Tunnel URL and runtime API key are ephemeral. If the Kaggle session restarts, update both repository secrets before the next model call.
