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

### Planned, not yet included

The master plan describes additional work such as model catalogue and hardware checks, an opt-in compute/farm mode with thermal safeguards, a complete worker lifecycle, dynamic CP pricing, richer chat settings, and automated Android APK builds with GitHub Actions. These features should not be assumed to be implemented in the current snapshot.

## Requirements

- Python 3.10 or newer is recommended.
- A working internet connection is needed to download the llama.cpp Android ARM64 binary and model files.
- Android deployment/building has not yet been configured in this repository.

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

The local model runner expects a GGUF model file. Select/provide a valid model path in the app before starting inference. The runner downloads an Android ARM64 `llama-server` release binary to `~/.mindpool/llama-server` when needed; this target is intended for Android ARM64 and may not run on a desktop Linux machine.

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

No license file is included in this repository snapshot yet. Until a license is added, all rights remain with the copyright holder; do not assume the project is MIT-licensed solely because the master plan mentions MIT.
