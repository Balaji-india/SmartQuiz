#!/usr/bin/env bash
# LINUX / macOS dev shortcuts (bash). The Windows equivalent is scripts/dev.ps1.
# Usage: ./scripts/dev.sh <setup|db|migrate|api|web|test>
set -euo pipefail
export PYTHONUTF8=1

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api_dir="$root/api"
web_dir="$root/web"
contracts_dir="$root/contracts"
python="$api_dir/.venv/bin/python"

case "${1:-}" in
  setup)
    # One-time install. Needs uv (https://docs.astral.sh/uv/); uses Python 3.12 like the Windows venv.
    cd "$api_dir"
    uv venv --python 3.12 .venv
    # unsafe-best-match lets uv take the CPU-only torch from the extra index in requirements.txt
    uv pip install --python "$python" --index-strategy unsafe-best-match -r requirements.txt
    (cd "$web_dir" && npm ci)
    (cd "$contracts_dir" && npm ci)
    [ -f "$web_dir/.env.local" ] || echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > "$web_dir/.env.local"
    ;;
  db)      cd "$root" && docker compose up -d db ;;
  migrate) cd "$api_dir" && "$python" -m alembic upgrade head ;;
  api)     cd "$api_dir" && exec "$python" -m uvicorn app.main:app --reload --port 8000 ;;
  web)     cd "$web_dir" && exec npm run dev ;;
  test)
    (cd "$api_dir" && "$python" -m pytest -q)
    (cd "$contracts_dir" && npx hardhat test)
    (cd "$web_dir" && npm run build)
    ;;
  *)
    echo "Usage: $0 <setup|db|migrate|api|web|test>" >&2
    exit 1
    ;;
esac
