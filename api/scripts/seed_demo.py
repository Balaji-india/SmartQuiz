"""Prepare the Review 1 stage demo through the running API (real LLM, real chain).

Creates (or logs in) the demo user, uploads and ingests the PDF, creates quiz 1 and waits until it is
ready WITHOUT starting it, so the timer is untouched for the stage. Prints the IDs, explorer links,
MetricsOut and timings to paste on stage. Upload is idempotent, so a re-run reuses the document.

Run the API first (CHAIN_OPTIONAL=false for the demo), then from api/:
  Linux:   PYTHONUTF8=1 .venv/bin/python scripts/seed_demo.py [--email demo@example.com] [--pdf ../samples/sample.pdf]
  Windows: $env:PYTHONUTF8=1; .\\.venv\\Scripts\\python.exe scripts\\seed_demo.py
The demo password comes from --password or SMARTQUIZ_DEMO_PASSWORD (default "review1-demo").
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLL_SEC = 3


class Api:
    def __init__(self, base: str):
        self.base, self.token = base.rstrip("/"), None

    def call(self, method: str, path: str, body=None, raw: bytes | None = None, content_type="application/json"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers = {"Content-Type": content_type} if data is not None else {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"{method} {path} → {e.code}: {e.read().decode(errors='replace')[:300]}") from None
        except urllib.error.URLError as e:
            raise SystemExit(f"Cannot reach the API at {self.base} ({e.reason}). Start it first.") from None

    def upload(self, path: Path):
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        return self.call("POST", "/documents", raw=body, content_type=f"multipart/form-data; boundary={boundary}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--email", default="demo@example.com")
    ap.add_argument("--password", default=os.environ.get("SMARTQUIZ_DEMO_PASSWORD", "review1-demo"))
    ap.add_argument("--name", default="Review 1 Demo")
    ap.add_argument("--pdf", default=str(ROOT / "samples" / "sample.pdf"))
    args = ap.parse_args()

    api = Api(args.api)
    pdf = Path(args.pdf)
    if not pdf.exists():
        raise SystemExit(f"{pdf} not found")
    print("health:", api.call("GET", "/health"))

    req = urllib.request.Request(
        api.base + "/auth/signup", method="POST", headers={"Content-Type": "application/json"},
        data=json.dumps({"email": args.email, "password": args.password, "name": args.name}).encode(),
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            api.token = json.load(r)["token"]
            print("signed up", args.email)
    except urllib.error.HTTPError as e:
        if e.code != 409:
            raise SystemExit(f"signup failed: {e.code} {e.read().decode(errors='replace')[:200]}")
        api.token = api.call("POST", "/auth/login", {"email": args.email, "password": args.password})["token"]
        print("logged in", args.email)

    t0 = time.time()
    doc = api.upload(pdf)
    while doc["status"] == "ingesting":
        time.sleep(POLL_SEC)
        doc = api.call("GET", f"/documents/{doc['id']}")
    ingest_sec = time.time() - t0
    if doc["status"] != "ready":
        raise SystemExit(f"ingestion {doc['status']}; see the API log")
    if doc["chain_status"] != "confirmed":
        print("registration is offline; retrying once")
        doc = api.call("POST", f"/documents/{doc['id']}/register")

    t1 = time.time()
    quiz = api.call("POST", "/quizzes", {"document_id": doc["id"], "num_questions": 10, "time_limit_sec": 600})
    last = None
    while True:
        p = api.call("GET", f"/quizzes/{quiz['id']}/progress")
        if p != last:
            print(f"  {time.time() - t1:5.0f}s {p['stage']:<10} accepted {p['accepted']}/{p['target']} rejected {p['rejected']}")
            last = p
        if p["stage"] in ("done", "failed"):
            break
        time.sleep(POLL_SEC)
    quiz_sec = time.time() - t1
    quiz = api.call("GET", f"/quizzes/{quiz['id']}")
    metrics = api.call("GET", f"/metrics/{doc['id']}")

    print("\n=== SmartQuiz Review 1 demo ===")
    print(f"user            {args.email}")
    print(f"document        {doc['id']}  ({doc['filename']})")
    print(f"  sections/facts {doc['sections_count']} / {doc['fact_count']}  dropped {doc['facts_dropped']}  unfaithful {doc['facts_unfaithful']}")
    print(f"  fact root     {doc['fact_root']}")
    print(f"  chain         {doc['chain_status']}  {doc['explorer_url']}")
    print(f"quiz 1          {quiz['id']}  status {quiz['status']} (NOT started)")
    print(f"  quiz hash     {quiz['quiz_hash']}")
    print(f"  chain         {quiz['chain_status']}  {quiz['explorer_url']}")
    print(f"  generation    {quiz['generation']}")
    print(f"timings         ingestion {ingest_sec:.0f}s, quiz generation {quiz_sec:.0f}s")
    print(f"web             http://localhost:3000/quiz/{quiz['id']}")
    print("MetricsOut:")
    print(json.dumps(metrics, indent=2))
    return 0 if quiz["status"] == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())
