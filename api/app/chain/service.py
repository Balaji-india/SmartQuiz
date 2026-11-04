"""SmartQuizRegistry over web3.py (SPEC section 6). The only code that talks to the chain.

One issuer wallet signs every transaction, so sends are serialised with a process-wide lock.
Only hashes leave the server. The private key is never logged.
"""
import json
import threading
import time
import uuid
from pathlib import Path

from eth_account import Account
from eth_utils import keccak
from web3 import Web3
from web3.exceptions import ContractCustomError, ContractLogicError
from web3.middleware import ExtraDataToPOAMiddleware

from app.config import get_settings

ABI_PATH = Path(__file__).parent / "abi" / "SmartQuizRegistry.json"
AMOY_CHAIN_ID = 80002
EXPLORER_TX = "https://amoy.polygonscan.com/tx/"
RECEIPT_TIMEOUT_SEC = 120
RPC_TIMEOUT_SEC = 10
LOG_LOOKBACK_BLOCKS = 9_000  # public RPCs cap eth_getLogs ranges
# Amoy rejects tips under 25 gwei; Hardhat accepts anything.
MIN_PRIORITY_FEE_WEI = {AMOY_CHAIN_ID: 25 * 10**9}

_send_lock = threading.Lock()


class ChainError(RuntimeError):
    """The chain is unreachable, misconfigured, or a transaction failed."""


def chain_id_of(value: uuid.UUID | str) -> str:
    """doc_id / quiz_id on chain = keccak256(utf-8 UUID string), lowercase 0x hex."""
    return "0x" + keccak(str(value).encode("utf-8")).hex()


def _b32(hex_str: str) -> bytes:
    raw = bytes.fromhex(hex_str.removeprefix("0x"))
    if len(raw) != 32:
        raise ValueError(f"expected 32 bytes, got {len(raw)}")
    return raw


def _hex(raw: bytes) -> str:
    return "0x" + bytes(raw).hex()


class ChainService:
    def __init__(self, rpc_url: str, private_key: str, registry_address: str):
        if not rpc_url or not private_key or not registry_address:
            raise ChainError("chain is not configured: AMOY_RPC_URL, ISSUER_PRIVATE_KEY and REGISTRY_ADDRESS are required")
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": RPC_TIMEOUT_SEC}))
        # Polygon is proof-of-authority: its block headers carry extra data web3 rejects otherwise.
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        try:
            self._account = Account.from_key(private_key)
        except Exception:
            # The exception text could contain key material; never pass it on.
            raise ChainError("ISSUER_PRIVATE_KEY is not a valid private key") from None
        self.address = Web3.to_checksum_address(registry_address)
        self.contract = self.w3.eth.contract(address=self.address, abi=json.loads(ABI_PATH.read_text("utf-8")))
        self._chain_id: int | None = None

    @property
    def issuer(self) -> str:
        return self._account.address

    @property
    def chain_id(self) -> int:
        if self._chain_id is None:
            try:
                self._chain_id = int(self.w3.eth.chain_id)
            except Exception as exc:
                raise ChainError(f"RPC unreachable: {type(exc).__name__}") from exc
        return self._chain_id

    def explorer_url(self, tx_hash: str | None) -> str | None:
        """Null unless the connected chain is Amoy (SPEC section 2)."""
        if not tx_hash:
            return None
        try:
            return f"{EXPLORER_TX}{tx_hash}" if self.chain_id == AMOY_CHAIN_ID else None
        except ChainError:
            return None

    # ---- writes -------------------------------------------------------------------------

    def _fees(self) -> dict:
        latest = self.w3.eth.get_block("latest")
        base = int(latest.get("baseFeePerGas") or 0)
        try:
            tip = int(self.w3.eth.max_priority_fee)
        except Exception:
            tip = 0
        tip = max(tip, MIN_PRIORITY_FEE_WEI.get(self.chain_id, 10**9))
        return {"maxPriorityFeePerGas": tip, "maxFeePerGas": 2 * base + tip}

    def _send(self, fn) -> str:
        with _send_lock:
            try:
                tx = fn.build_transaction(
                    {
                        "from": self.issuer,
                        "chainId": self.chain_id,
                        "nonce": self.w3.eth.get_transaction_count(self.issuer, "pending"),
                        **self._fees(),
                    }
                )
                tx["gas"] = int(self.w3.eth.estimate_gas(tx) * 1.2)
                signed = self._account.sign_transaction(tx)
                tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            except (ContractLogicError, ContractCustomError) as exc:
                raise ChainError(f"transaction would revert: {self._revert_name(exc)}") from exc
            except ChainError:
                raise
            except Exception as exc:
                raise ChainError(f"could not send transaction: {type(exc).__name__}") from exc
            # Wait inside the lock, so the next nonce never races a pending one.
            try:
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=RECEIPT_TIMEOUT_SEC)
            except Exception as exc:
                raise ChainError(f"no receipt for {_hex(tx_hash)} within {RECEIPT_TIMEOUT_SEC}s") from exc
        if receipt["status"] != 1:
            raise ChainError(f"transaction {_hex(tx_hash)} reverted")
        return _hex(tx_hash)

    def _revert_name(self, exc: Exception) -> str:
        data = getattr(exc, "data", None)
        if isinstance(data, dict):  # Hardhat wraps the revert data: {"message": ..., "data": "0x..."}
            data = data.get("data")
        if isinstance(data, str) and len(data) >= 10:
            for item in self.contract.abi:
                if item.get("type") == "error":
                    sig = f"{item['name']}({','.join(i['type'] for i in item['inputs'])})"
                    if data[:10] == "0x" + keccak(text=sig).hex()[:8]:
                        return item["name"]
        return type(exc).__name__

    def register_document(self, document_uuid: uuid.UUID | str, fact_root: str, fact_count: int) -> str:
        existing = self.get_document(document_uuid)
        if existing is not None:
            # An earlier send may have landed after its receipt wait timed out: recover its tx hash.
            if existing[0] != fact_root.lower():
                raise ChainError("document is already registered on chain with a different root")
            return self._find_register_tx(document_uuid)
        fn = self.contract.functions.registerDocument(
            _b32(chain_id_of(document_uuid)), _b32(fact_root), int(fact_count)
        )
        return self._send(fn)

    def commit_quiz(self, quiz_uuid: uuid.UUID | str, document_uuid: uuid.UUID | str, quiz_hash: str) -> str:
        fn = self.contract.functions.commitQuiz(
            _b32(chain_id_of(quiz_uuid)), _b32(chain_id_of(document_uuid)), _b32(quiz_hash)
        )
        return self._send(fn)

    def _find_register_tx(self, document_uuid: uuid.UUID | str) -> str:
        try:
            latest = self.w3.eth.block_number
            logs = self.contract.events.DocumentRegistered.get_logs(
                argument_filters={"docId": _b32(chain_id_of(document_uuid))},
                from_block=max(latest - LOG_LOOKBACK_BLOCKS, 0),
                to_block=latest,
            )
        except Exception as exc:
            raise ChainError(f"registered on chain, but its tx could not be looked up: {type(exc).__name__}") from exc
        if not logs:
            raise ChainError("registered on chain, but its tx is older than the lookup window")
        return _hex(logs[-1]["transactionHash"])

    # ---- reads --------------------------------------------------------------------------

    def _call(self, fn):
        try:
            return fn.call()
        except Exception as exc:
            raise ChainError(f"chain read failed: {type(exc).__name__}") from exc

    def verify_fact(self, document_uuid: uuid.UUID | str, leaf: str, proof: list[str]) -> bool:
        fn = self.contract.functions.verifyFact(
            _b32(chain_id_of(document_uuid)), _b32(leaf), [_b32(p) for p in proof]
        )
        return bool(self._call(fn))

    def get_document(self, document_uuid: uuid.UUID | str) -> tuple[str, int, int] | None:
        """(fact_root, fact_count, registered_at), or None if the document is not registered."""
        root, count, at = self._call(self.contract.functions.getDocument(_b32(chain_id_of(document_uuid))))
        return None if at == 0 else (_hex(root), int(count), int(at))

    def get_quiz(self, quiz_uuid: uuid.UUID | str) -> tuple[str, str, int] | None:
        """(doc_id, quiz_hash, committed_at), or None if the quiz is not committed."""
        doc, quiz_hash, at = self._call(self.contract.functions.getQuiz(_b32(chain_id_of(quiz_uuid))))
        return None if at == 0 else (_hex(doc), _hex(quiz_hash), int(at))


_service_lock = threading.Lock()
_service: ChainService | None = None
_failed_at: float = 0.0
# After a configuration or connection failure, fail fast for a while instead of waiting on the RPC each time.
RETRY_AFTER_FAILURE_SEC = 30


def get_chain() -> ChainService:
    """The process-wide ChainService. Raises ChainError if the chain is not configured or unreachable."""
    global _service, _failed_at
    with _service_lock:
        if _service is not None:
            return _service
        if time.monotonic() - _failed_at < RETRY_AFTER_FAILURE_SEC and _failed_at:
            raise ChainError("chain unavailable (recent failure)")
        s = get_settings()
        try:
            service = ChainService(s.amoy_rpc_url, s.issuer_private_key, s.registry_address)
            service.chain_id  # connect once, so an unreachable RPC is reported here
        except ChainError:
            _failed_at = time.monotonic()
            raise
        _service = service
        return service


def reset_chain() -> None:
    """Forget the cached service (tests, or after .env changes)."""
    global _service, _failed_at
    with _service_lock:
        _service, _failed_at = None, 0.0


def explorer_url(tx_hash: str | None) -> str | None:
    if not tx_hash:
        return None
    try:
        return get_chain().explorer_url(tx_hash)
    except ChainError:
        return None

