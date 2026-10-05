# GandyTrade Lab: notes for Claude

Private, single-user beginner trading lab at https://gandytrade.co.uk (UK owner, GBP).
Current state and next steps: `docs/HANDOVER.md` (read first). Roadmap: `docs/ROADMAP.md`. Deployment: `docs/DEPLOY.md`.

## Hard rules
- **No real-money order code** outside `backend/app/live/` (Phase 6 only). `tests/test_safety.py` enforces it.
- **All outbound HTTP** goes through `market/providers/http.py::safe_client` (host allowlist). Never add hosts casually.
- **Evidence, not advice.** The app shows rule checklists and historical results; it never says "buy now".
- **Risk guard on every simulated order:** stop-loss required, default 1% risk, daily and drawdown limits, leverage caps.
- **Honest results:** spreads, commission, slippage (and stamp duty / financing where relevant) always included; always compared with buy-and-hold.
- **Shared cPanel server:** no server-wide changes. Everything runs as the `gandytradeco` user in rootless Podman.
- **Secrets** live only in `~/gandytrade/app.env` on the server (mode 600). Never in the repo, logs, chat or screenshots.
- **Free data services only**: OANDA practice (forex, metals, commodities, indices, bonds), Twelve Data free (US stocks/ETFs), Alpha Vantage free (FTSE 100, daily/weekly/monthly, 25 requests/day).

## Working on the code
- Backend: Python 3.12, FastAPI, SQLAlchemy 2, pandas. Tests: `cd backend && python -m pytest -q`.
- Frontend: React 18 + TypeScript + Vite + Lightweight Charts v5. `cd frontend && npm run build`.
- **Table changes need a migration** in `backend/app/migrations/versions/` (next number, hand-written).
  `tests/test_migrations.py` fails if models and migrations disagree. Migrations run at app start-up;
  `deploy/scripts/update.sh` backs up the database first.
- Python dependencies: edit `backend/requirements.in`, then regenerate hashed `requirements.txt` with
  `uv pip compile requirements.in --python-version 3.12 --python-platform linux --generate-hashes`.
- CI (GitHub Actions): backend tests, frontend build, gitleaks secret scan.
- Plain British English in the UI; explain trading terms for a beginner.
