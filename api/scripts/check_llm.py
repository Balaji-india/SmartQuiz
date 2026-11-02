"""Check both LLM keys and model names. Prints no key values."""
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import OpenAI  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.llm.provider import model_family, parse_json, role_config, same_family_checker  # noqa: E402

ENV_LINE = {"generator": "LLM_GENERATOR_MODEL", "checker": "LLM_CHECKER_MODEL"}


def check(role: str) -> bool:
    cfg = role_config(role)
    print(f"--- {role}: {cfg.base_url}")
    if not cfg.api_key:
        print("  key is empty: FAKE mode, skipped")
        return False
    client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, max_retries=1, timeout=60)
    try:
        names = sorted(m.id.removeprefix("models/") for m in client.models.list())
    except Exception as exc:
        print(f"  could not list models: {type(exc).__name__} {getattr(exc, 'status_code', '')}")
        return False
    print(f"  {len(names)} models available")
    if cfg.model.removeprefix("models/") not in names:
        print(f"  MISSING: {cfg.model}")
        print(f"  closest available: {difflib.get_close_matches(cfg.model, names, n=5, cutoff=0.3)}")
        print(f"  change the {ENV_LINE[role]} line in .env")
        return False
    print(f"  model found: {cfg.model}")
    try:
        reply = client.chat.completions.create(
            model=cfg.model,
            messages=[
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": 'Return exactly {"ok": true}'},
            ],
            response_format={"type": "json_object"},
        )
        print(f"  JSON request ok: {parse_json(reply.choices[0].message.content or '')}")
    except Exception as exc:
        print(f"  JSON request failed: {type(exc).__name__} {getattr(exc, 'status_code', '')}")
        return False
    return True


def main() -> int:
    get_settings()
    results = [check("generator"), check("checker")]
    families = model_family(role_config("generator").model), model_family(role_config("checker").model)
    print(f"model families: generator={families[0]} checker={families[1]}")
    if same_family_checker():
        print("WARNING: same model family, so checker independence is lost (SPEC section 4)")
    print("RESULT:", "both OK" if all(results) else "problem found, see above")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
