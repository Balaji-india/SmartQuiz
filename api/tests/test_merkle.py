import pytest
from eth_utils import keccak

from app.chain import merkle


def make_leaves(n):
    return [merkle.leaf(i, merkle.text_hash(f"fact number {i}")) for i in range(n)]


def parent(a, b):
    x, y = bytes.fromhex(a[2:]), bytes.fromhex(b[2:])
    return "0x" + keccak(min(x, y) + max(x, y)).hex()


@pytest.mark.parametrize("n", [1, 2, 3, 7])
def test_every_proof_verifies(n):
    leaves = make_leaves(n)
    root = merkle.build_tree(leaves)
    for i, lf in enumerate(leaves):
        assert merkle.verify(root, lf, merkle.proof(leaves, i))


@pytest.mark.parametrize("n", [1, 2, 3, 7])
def test_tampered_leaf_fails(n):
    leaves = make_leaves(n)
    root = merkle.build_tree(leaves)
    tampered = merkle.leaf(0, merkle.text_hash("fact number 0, edited"))
    assert not merkle.verify(root, tampered, merkle.proof(leaves, 0))


def test_one_leaf_root_is_the_leaf():
    leaves = make_leaves(1)
    assert merkle.build_tree(leaves) == leaves[0]
    assert merkle.proof(leaves, 0) == []


def test_odd_node_promoted_unchanged():
    a, b, c = make_leaves(3)
    assert merkle.build_tree([a, b, c]) == parent(parent(a, b), c)
    assert merkle.proof([a, b, c], 2) == [parent(a, b)]  # nothing added at the promoted level


def test_seven_leaf_shape():
    ls = make_leaves(7)
    left = parent(parent(ls[0], ls[1]), parent(ls[2], ls[3]))
    right = parent(parent(ls[4], ls[5]), ls[6])
    assert merkle.build_tree(ls) == parent(left, right)
    assert merkle.proof(ls, 6) == [parent(ls[4], ls[5]), left]


def test_root_identical_across_runs():
    assert merkle.build_tree(make_leaves(7)) == merkle.build_tree(make_leaves(7))


def test_changing_leaf_order_changes_root():
    leaves = make_leaves(7)
    swapped = [leaves[2], *leaves[:2], *leaves[3:]]
    assert merkle.build_tree(leaves) != merkle.build_tree(swapped)


def test_idx_is_bound_into_the_leaf():
    th = merkle.text_hash("same text")
    assert merkle.leaf(0, th) != merkle.leaf(1, th)


def test_leaf_is_the_openzeppelin_format():
    th = merkle.text_hash("x")
    encoded = (5).to_bytes(32, "big") + bytes.fromhex(th[2:])
    assert merkle.leaf(5, th) == "0x" + keccak(keccak(encoded)).hex()


def test_hex_is_lowercase_with_prefix():
    h = merkle.text_hash("Fact")
    assert h.startswith("0x") and h == h.lower() and len(h) == 66


def test_zero_leaves_is_an_error():
    with pytest.raises(ValueError):
        merkle.build_tree([])
