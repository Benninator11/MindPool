# MindPool

MindPool is an early-stage Python project exploring a decentralized network in which phones can run small language models locally and make their compute capacity available to other users.

The repository currently contains an initial Flet mobile-app prototype, a local `llama-server` runner, a FastAPI/WebSocket broker prototype, and the project master plan. **It is not yet a complete or production-ready decentralized AI network.**

## Project structure

```text
MindPool/
├── backend/
│   ├── main.py                 # FastAPI API and WebSocket broker prototype
│   ├── database.py             # SQLite persistence, accounts, devices and CP ledger
│   └── requirements.txt
├── mobile_app/
│   ├── main.py                 # Flet application prototype
│   ├── engine/
│   │   └── llama_runner.py     # Starts llama-server and streams local chat output
│   └── requirements.txt
├── MindPool_Masterplan_2.0.txt # Architecture and planned development steps
├── .gitignore
└── README.md
```

## Current components

### Mobile app
- Python UI built with Flet.
- Dark interface prototype.
- Local inference integration through an OpenAI-compatible `llama-server` endpoint.
- Streaming chat responses through `httpx`.
- Model download helper.

### Backend
- FastAPI HTTP API and WebSocket endpoint.
- Username/password registration and login.
- Argon2 password hashing and recovery keys.
- Device registration and device limits.
- SQLite-backed Compute Points (CP) balance and transaction records.
- Initial pool-job endpoints and matchmaking/relay scaffolding.

### Planned or incomplete

The master plan remains a roadmap. The local model catalogue, Android hardware-sensor integration, full worker inference loop, dynamic CP pricing, and account/device screens are not yet complete. The current farm controller is a safety-checked foundation and is not yet connected to the main app screen.

## Requirements

- Python 3.10 or newer is recommended.
- A working internet connection is needed to download the llama.cpp Android ARM64 binary and model files.
- Android APK builds are configured through GitHub Actions; a successful build does not by itself prove that on-device inference or networking works.

## Run the backend locally

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Set a private JWT signing key before starting the service:

```bash
export JWT_SECRET="replace-this-with-a-long-random-secret"
```

Start the API:

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Health endpoint: `http://127.0.0.1:8000/health`

Interactive API documentation: `http://127.0.0.1:8000/docs`

> **Security warning:** This is a development prototype. Do not expose it to the public internet or use real accounts until authentication, authorization, job assignment, CP accounting, input validation, rate limiting, secret management, and deployment security have been reviewed and tested. Never use the development JWT fallback secret in a deployed environment.

## Run the mobile prototype

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r mobile_app/requirements.txt
cd mobile_app
python main.py
```

The local model runner expects a GGUF model file under `~/.mindpool/models`. The app currently has no in-app model-import screen, so a model must be placed there manually. On Android, the runner can attempt to download the configured Android ARM64 `llama-server` binary. On desktop Linux and other systems it will not mistakenly download that Android executable; provide a compatible executable with `MINDPOOL_LLAMA_SERVER` or a trusted download URL with `MINDPOOL_LLAMA_SERVER_URL`. Android runtime execution still needs device testing.

## Database

The backend creates its SQLite database automatically on first startup. By default it uses `mindpool.db` in the current working directory. Set `DATABASE_PATH` to choose another location:

```bash
export DATABASE_PATH="$HOME/.local/share/mindpool/mindpool.db"
```

Database files are intentionally excluded from version control. They can contain account records, password hashes, recovery keys, device identifiers, sessions, prompts, and job results. Do not commit a live database.

## Compute Points

The current code contains an initial CP balance and transaction ledger. The intended project design describes CP as non-transferable credits for verified completed compute work. The current prototype should not yet be treated as a secure or audited payment/reward system.

## Development status

MindPool is under active development. Interfaces and APIs may change. The master plan is a roadmap, not a guarantee that every listed feature exists in the current code.

Contributions, bug reports, and implementation feedback are welcome.

## License

This project is distributed under the MIT License; see [`LICENSE`](LICENSE).


## Additional modules

The repository also includes the following early foundations:

- `mobile_app/engine/model_manager.py`: local GGUF inventory, configurable model-count limit, explicit HTTPS download and removal. The catalogue entries intentionally have no download URLs until the exact model files and their licenses are verified.
- `mobile_app/engine/hardware_guard.py`: conservative checks for battery, temperature, charging and Wi-Fi. Missing sensor readings block worker start.
- `mobile_app/network/broker_client.py`: authenticated WebSocket client for the broker.
- `mobile_app/ui/farm_view.py`: explicit opt-in farm-session controller with Eco/Balanced/Turbo modes and safety checks.
- `mobile_app/ui/wallet_view.py`: Compute Points display data helpers.
- `.github/workflows/build_apk.yml`: GitHub Actions workflow that attempts an Android APK build on relevant pushes and manual dispatch.
- `LICENSE`: MIT License.

## Build the Android APK

Open the repository's **Actions** tab and select **Build MindPool Android APK**, then choose **Run workflow**. A successful build publishes a temporary downloadable artifact named `MindPool-Android-APK`. Pushes affecting `mobile_app/**` also trigger the workflow.

The first workflow run is the real compatibility check: Flet's Android build may require adjustments to SDK/build dependencies or project configuration. A workflow file being present does not mean an APK has already built successfully.

## Important implementation limits

These additions are foundations, not a finished distributed compute marketplace. The farm controller is not yet wired into the main Flet screen, and a complete worker loop/job execution protocol still needs implementation. The broker currently has prototype-level authentication and job routing; do not expose it publicly or use it for real accounts or sensitive prompts. Hardware sensor acquisition is platform-specific and must be connected to verified Android APIs before worker mode can be enabled in a release.


### Supported compute platforms

MindPool's compute/farm platform check permits Android and 64-bit Raspberry Pi OS
(aarch64/arm64). Raspberry Pi devices are detected through the Linux device-tree
model string. Other desktop Linux distributions and non-ARM64 systems are not
enabled for farm mode by this check.

On Raspberry Pi, install a native Linux ARM64 `llama-server` build and set
`MINDPOOL_LLAMA_SERVER` to its executable path before starting local inference.
The Android `llama-server` binary is not compatible with Raspberry Pi OS.
