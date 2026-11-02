"""The only Merkle implementation (SPEC section 8). All hashes are lowercase 0x hex.

Leaves stay in idx order. Parents hash the sorted pair; an odd last node is promoted
unchanged. Proofs verify with Solidity's MerkleProof.verify.
"""
from eth_abi import encode
from eth_utils import keccak


def _b(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str.removeprefix("0x"))


def _h(data: bytes) -> str:
    return "0x" + data.hex()


def _parent(a: bytes, b: bytes) -> bytes:
    return keccak(min(a, b) + max(a, b))


def text_hash(text: str) -> str:
    return _h(keccak(text.encode("utf-8")))


def leaf(idx: int, text_hash: str) -> str:
    inner = keccak(encode(["uint256", "bytes32"], [idx, _b(text_hash)]))
    return _h(keccak(inner))


def _next_level(level: list[bytes]) -> list[bytes]:
    parents = [_parent(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
    if len(level) % 2:
        parents.append(level[-1])
    return parents


def build_tree(leaves: list[str]) -> str:
    if not leaves:
        raise ValueError("cannot build a Merkle tree from zero leaves")
    level = [_b(x) for x in leaves]
    while len(level) > 1:
        level = _next_level(level)
    return _h(level[0])


def proof(leaves: list[str], index: int) -> list[str]:
    if not 0 <= index < len(leaves):
        raise IndexError(f"leaf index {index} out of range for {len(leaves)} leaves")
    level = [_b(x) for x in leaves]
    siblings: list[str] = []
    while len(level) > 1:
        sibling = index ^ 1
        if sibling < len(level):  # otherwise this node is promoted: nothing to add
            siblings.append(_h(level[sibling]))
        level = _next_level(level)
        index //= 2
    return siblings


def verify(root: str, leaf: str, proof: list[str]) -> bool:
    node = _b(leaf)
    for sibling in proof:
        node = _parent(node, _b(sibling))
    return _h(node) == root.lower()
