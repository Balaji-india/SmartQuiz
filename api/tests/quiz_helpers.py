"""Shared setup for quiz tests: a FAKE-ingested document with varied facts across four sections."""
import io

from tests.conftest import signup_headers

# FAKE extraction turns each sentence of 5+ words into a fact whose concept is its first three words,
# so every sentence starts differently and covers a different topic (no cosine duplicates).
NOTES = """1 Operating Systems
Round robin scheduling gives every process an equal fixed time slice.
Paging splits physical memory into frames of one fixed size.
Deadlock needs mutual exclusion, hold and wait, no preemption and circular wait.
Thrashing occurs when a machine spends more time swapping pages than running code.
Semaphores are integer counters changed only through wait and signal operations.
Interrupt handlers save the registers before servicing a hardware device.

2 Networks
TCP guarantees ordered delivery using sequence numbers and acknowledgements.
Routers forward packets between networks by reading destination IP addresses.
DNS translates human readable domain names into numeric addresses.
Ethernet frames carry a source and destination MAC address in their header.
Firewalls filter inbound traffic according to an ordered list of rules.
Latency measures how long one packet takes to cross the network.

3 Databases
Primary keys identify each table row uniquely and cannot be null.
Normalisation removes redundant columns by splitting tables apart.
Indexes speed up lookups at the cost of slower writes and extra storage.
Transactions follow ACID: atomicity, consistency, isolation and durability.
Foreign keys enforce that a referenced row exists in the parent table.
Query planners choose join orders by estimating the cost of each plan.

4 Security
Phishing emails trick people into revealing passwords on fake websites.
Ransomware encrypts a victim's files and demands payment for the key.
Two factor authentication combines a password with a second proof such as a phone.
Hashing passwords with a slow salted function resists offline cracking.
Least privilege gives each account only the access its job requires.
Patching software promptly closes vulnerabilities that attackers already know.
"""


def ready_document(client, email="a@b.com") -> tuple[dict, str]:
    headers = signup_headers(client, email)
    doc = client.post(
        "/documents", files={"file": ("notes.txt", io.BytesIO(NOTES.encode("utf-8")))}, headers=headers
    ).json()
    doc = client.get(f"/documents/{doc['id']}", headers=headers).json()
    assert doc["status"] == "ready", doc
    return headers, doc["id"]


def make_quiz(client, headers, document_id, n=5, time_limit_sec=600) -> dict:
    created = client.post(
        "/quizzes", json={"document_id": document_id, "num_questions": n, "time_limit_sec": time_limit_sec}, headers=headers
    ).json()
    # TestClient runs the background job before returning, so the quiz is finished here.
    return created
