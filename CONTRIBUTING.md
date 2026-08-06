# Contributing to Giljo HQ

Thank you for your interest in Giljo HQ, a GiljoAI product.

## Before You Contribute

Read this section first. It affects your intellectual property rights.

### Intellectual Property Assignment

By submitting a pull request, patch, or any other contribution to this
repository, You irrevocably assign all intellectual property rights in
Your contribution to GiljoAI LLC. You represent that You have the right
to make such assignment. GiljoAI LLC may use, license, and sublicense
Your contribution without restriction, including in proprietary and
commercial products.

You retain the right to use Your own contributions in Your other projects.

This assignment is necessary because GiljoAI distributes the Software under
both the GiljoAI Community License (free for single-user use) and commercial
licenses. Without full IP ownership of every line of code, we cannot offer
commercial licenses. This is standard practice for dual-licensed projects.

If you do not agree with these terms, please do not submit contributions.
You are welcome to fork the repository and use it under the terms of the
[LICENSE](LICENSE).

## Development Setup

**Requirements**: Python 3.12+, PostgreSQL 18, Node.js 22+

```bash
# Clone and install
git clone https://github.com/giljoai/giljo-hq.git
cd giljo-hq
python install.py          # Interactive installer (sets up config.yaml, DB, etc.)

# Install dependencies
pip install -r requirements.txt
pip install -r dev-requirements.txt
cd frontend && npm install && cd ..
```

### Production mode (single port)

In production, FastAPI serves both the API and the built frontend on port **7272**:

```bash
cd frontend && npm run build && cd ..   # Build frontend into frontend/dist/
python startup.py                        # Starts on :7272 (API + frontend)
```

Open `http://127.0.0.1:7272` to access the full application.

### Development mode (two ports, hot-reload)

For active development, use `--dev` to run the Vite dev server alongside the API:

```bash
python startup.py --dev
```

This starts:
- **Port 7272** -- FastAPI API server
- **Port 7274** -- Vite dev server with hot module replacement

Open `http://127.0.0.1:7274` for the frontend (proxies API calls to 7272).

To switch from production back to dev mode, simply re-run with `--dev`. No build step needed.

## Code Style

- **Python**: Enforced by [ruff](https://docs.astral.sh/ruff/) (linting and formatting)
- **Frontend**: Enforced by ESLint (`eslint.config.js` flat config)
- **Paths**: Always use `pathlib.Path()` — never hardcode OS-specific paths
- **Logging**: Use `import logging; logger = logging.getLogger(__name__)` in most code. Use `structlog` only in auth, database, WebSocket, and MCP orchestration paths.

For the conventions behind these rules — service and repository layering, database write discipline, tenant isolation, and frontend structure — see **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**. For the security posture a change is expected to preserve, see **[docs/SECURITY_POSTURE.md](docs/SECURITY_POSTURE.md)**.

Run before committing:
```bash
python -m ruff check src/ api/
python -m ruff format src/ api/
cd frontend && npx eslint src/ --fix
```

## Submitting a Pull Request

1. Create a feature branch from `master`: `git checkout -b feature/short-description`
2. Make your changes following the code style above
3. Run tests: `pytest tests/ -x`
4. Verify frontend builds: `cd frontend && npm run build`
5. Commit using [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
6. Push and open a PR against `master`

## Testing

- Run full suite: `pytest tests/ --cov=src/giljo_mcp`
- Coverage target: >80% for new code
- Tests use PostgreSQL with transaction rollback for isolation

## Architecture

- **Service layer**: Business logic in `src/giljo_mcp/services/`. Services raise domain exceptions from `src/giljo_mcp/exceptions.py`.
- **API layer**: FastAPI endpoints in `api/endpoints/`. Global exception handlers map domain exceptions to HTTP status codes.
- **Frontend**: Vue 3 + Vuetify + Pinia stores in `frontend/src/`.
- **Data isolation**: All database queries filter by `tenant_key`. Never bypass tenant isolation.

See `docs/README_FIRST.md` for navigation and `docs/ARCHITECTURE.md` for full architecture.

## Reporting Issues

Use [GitHub Issues](https://github.com/giljoai/giljo-hq/issues) with the provided templates. Include steps to reproduce for bugs.

## Security Vulnerabilities

See [SECURITY.md](SECURITY.md) for responsible disclosure process. Do not open public issues for security vulnerabilities.
