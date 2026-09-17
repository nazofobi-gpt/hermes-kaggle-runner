# hermes-kaggle-runner

Public GitHub Actions runner for controlled remote tasks and authenticated calls to an ephemeral Kaggle GPU model endpoint.

## Required repository secrets

Create these under **Settings → Secrets and variables → Actions**. Never commit their values.

- `KAGGLE_API_TOKEN` — one-time Kaggle API credential used by GitHub Actions to start/update the private Kaggle worker kernel.
- `KAGGLE_BASE_URL` — current OpenAI-compatible endpoint; the Kaggle worker refreshes this automatically after it creates/restarts a Quick Tunnel.
- `KAGGLE_API_KEY` — current Bearer token; the Kaggle worker refreshes this automatically.

The private Kaggle worker also expects the Kaggle Secret `GITHUB_SYNC_TOKEN` so it can update only `KAGGLE_BASE_URL` and `KAGGLE_API_KEY` in this repository.

## Autonomous GPU control

`control/kaggle_state.json` is the desired-state control plane.

- `RUN` with a new `generation` triggers **Kaggle GPU Control**, which uses the official Kaggle CLI to upload/run the private `hermes-gpu-worker` kernel on a T4 GPU.
- `STOP` is observed by the running Kaggle worker, which terminates itself.
- The worker has a six-hour fail-safe maximum runtime and polls the control file every 30 seconds.
- If a Cloudflare Quick Tunnel dies while the worker is alive, it creates another tunnel and refreshes the GitHub endpoint secrets.

## Other workflows

- **Remote Terminal** runs `commands/run.sh` on a fresh Ubuntu GitHub-hosted runner.
- **Kaggle Model Call** sends `requests/prompt.txt` to the configured Kaggle endpoint with model `llama3.1-hermes`.
- **Hermes Public Task** runs a guarded Hermes Agent task against the Kaggle model endpoint.

The repository is public. Do not place private documents, credentials, or sensitive task content in committed files or public Actions logs.
