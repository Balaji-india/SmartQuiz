// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";
import {Base64} from "@openzeppelin/contracts/utils/Base64.sol";
import {Strings} from "@openzeppelin/contracts/utils/Strings.sol";

/// @notice The part of SmartQuizRegistry this contract reads (the registry itself is unchanged).
interface ISmartQuizRegistry {
    function getDocument(bytes32 docId) external view returns (bytes32 factRoot, uint32 factCount, uint64 registeredAt);
}

/// @title SmartQuizCredentials (SPEC 9.8)
/// @notice Result batches (Merkle roots of attempt hashes), soulbound ERC-5192 concept badges, and educator
/// co-signing / revocation authorised by EIP-712 signatures. The owner (the issuer wallet) sends every tx;
/// educators only sign. Only hashes and addresses are stored: no document, concept or learner text.
contract SmartQuizCredentials is Ownable, ERC721, EIP712 {
    struct Batch {
        bytes32 root;
        uint32 count;
        uint64 anchoredAt;
    }

    struct Badge {
        bytes32 docId;
        bytes32 conceptHash;
        bytes32 evidenceHash;
        uint64 issuedAt;
        bool revoked;
    }

    struct CoSign {
        address educator;
        uint64 at;
    }

    bytes32 public constant REVOKE_BADGE_TYPEHASH = keccak256("RevokeBadge(uint256 tokenId,bytes32 reasonHash)");
    bytes32 public constant COSIGN_TYPEHASH = keccak256("CoSign(bytes32 docId,bytes32 factRoot)");
    bytes32 public constant REVOKE_DOCUMENT_TYPEHASH = keccak256("RevokeDocument(bytes32 docId,bytes32 reasonHash)");
    bytes4 private constant ERC5192_INTERFACE_ID = 0xb45a3c0e;

    ISmartQuizRegistry public immutable registry;

    mapping(address => bool) private _educators;
    mapping(bytes32 => Batch) private _batches;
    mapping(uint256 => Badge) private _badges;
    mapping(bytes32 => CoSign) private _coSigns;
    mapping(bytes32 => bool) private _revokedDocuments;
    uint256 private _nextTokenId = 1;

    event EducatorAdded(address indexed educator);
    event EducatorRemoved(address indexed educator);
    event ResultsAnchored(bytes32 indexed batchId, bytes32 root, uint32 count);
    event BadgeMinted(uint256 indexed tokenId, address indexed to, bytes32 docId, bytes32 conceptHash, bytes32 evidenceHash);
    /// @dev ERC-5192
    event Locked(uint256 tokenId);
    event BadgeRevoked(uint256 indexed tokenId, bytes32 reasonHash, address indexed educator);
    event DocumentCoSigned(bytes32 indexed docId, bytes32 factRoot, address indexed educator);
    event DocumentRevoked(bytes32 indexed docId, bytes32 reasonHash, address indexed educator);

    error NotEducator(address signer);
    error BatchExists(bytes32 batchId);
    error UnknownBatch(bytes32 batchId);
    error Soulbound();
    error RootMismatch(bytes32 registryRoot, bytes32 given);
    error AlreadyRevoked();
    error UnknownToken(uint256 tokenId);

    constructor(address initialOwner, address registry_)
        Ownable(initialOwner)
        ERC721("SmartQuiz Concept Badge", "SQB")
        EIP712("SmartQuizCredentials", "1")
    {
        registry = ISmartQuizRegistry(registry_);
    }

    // ---- educators ----
    function addEducator(address e) external onlyOwner {
        _educators[e] = true;
        emit EducatorAdded(e);
    }

    function removeEducator(address e) external onlyOwner {
        _educators[e] = false;
        emit EducatorRemoved(e);
    }

    function isEducator(address e) external view returns (bool) {
        return _educators[e];
    }

    // ---- result batches ----
    function anchorResults(bytes32 batchId, bytes32 root, uint32 count) external onlyOwner {
        if (_batches[batchId].anchoredAt != 0) revert BatchExists(batchId);
        _batches[batchId] = Batch(root, count, uint64(block.timestamp));
        emit ResultsAnchored(batchId, root, count);
    }

    /// @notice True if `leaf` (an attempt-hash leaf, SPEC 9.9) is in the batch's tree. Reverts for an unknown batch.
    function verifyResult(bytes32 batchId, bytes32 leaf, bytes32[] calldata proof) external view returns (bool) {
        Batch storage b = _batches[batchId];
        if (b.anchoredAt == 0) revert UnknownBatch(batchId);
        return MerkleProof.verifyCalldata(proof, b.root, leaf);
    }

    function getBatch(bytes32 batchId) external view returns (bytes32 root, uint32 count, uint64 anchoredAt) {
        Batch storage b = _batches[batchId];
        return (b.root, b.count, b.anchoredAt);
    }

    // ---- soulbound badges (ERC-5192) ----
    function mintBadge(address to, bytes32 docId, bytes32 conceptHash, bytes32 evidenceHash)
        external
        onlyOwner
        returns (uint256 tokenId)
    {
        tokenId = _nextTokenId++;
        _badges[tokenId] = Badge(docId, conceptHash, evidenceHash, uint64(block.timestamp), false);
        _mint(to, tokenId);
        emit BadgeMinted(tokenId, to, docId, conceptHash, evidenceHash);
        emit Locked(tokenId);
    }

    function locked(uint256 tokenId) external view returns (bool) {
        _requireBadge(tokenId);
        return true;
    }

    function getBadge(uint256 tokenId)
        external
        view
        returns (bytes32 docId, bytes32 conceptHash, bytes32 evidenceHash, uint64 issuedAt, bool revoked)
    {
        _requireBadge(tokenId);
        Badge storage b = _badges[tokenId];
        return (b.docId, b.conceptHash, b.evidenceHash, b.issuedAt, b.revoked);
    }

    /// @notice Marks a badge revoked (kept, not burned). `educatorSig` is an EIP-712 RevokeBadge signature.
    function revokeBadge(uint256 tokenId, bytes32 reasonHash, bytes calldata educatorSig) external onlyOwner {
        _requireBadge(tokenId);
        Badge storage b = _badges[tokenId];
        if (b.revoked) revert AlreadyRevoked();
        address educator = _educatorSigner(keccak256(abi.encode(REVOKE_BADGE_TYPEHASH, tokenId, reasonHash)), educatorSig);
        b.revoked = true;
        emit BadgeRevoked(tokenId, reasonHash, educator);
    }

    // ---- documents: co-sign and revocation ----
    /// @notice Records an educator's EIP-712 CoSign of a document. `factRoot` must equal the registry's root
    /// (an unregistered document has root 0, so it never matches a real root).
    function coSignDocument(bytes32 docId, bytes32 factRoot, bytes calldata educatorSig) external onlyOwner {
        (bytes32 registryRoot,,) = registry.getDocument(docId);
        if (registryRoot != factRoot || factRoot == bytes32(0)) revert RootMismatch(registryRoot, factRoot);
        address educator = _educatorSigner(keccak256(abi.encode(COSIGN_TYPEHASH, docId, factRoot)), educatorSig);
        _coSigns[docId] = CoSign(educator, uint64(block.timestamp));
        emit DocumentCoSigned(docId, factRoot, educator);
    }

    function getCoSign(bytes32 docId) external view returns (address educator, uint64 at) {
        CoSign storage c = _coSigns[docId];
        return (c.educator, c.at);
    }

    function revokeDocument(bytes32 docId, bytes32 reasonHash, bytes calldata educatorSig) external onlyOwner {
        if (_revokedDocuments[docId]) revert AlreadyRevoked();
        address educator = _educatorSigner(keccak256(abi.encode(REVOKE_DOCUMENT_TYPEHASH, docId, reasonHash)), educatorSig);
        _revokedDocuments[docId] = true;
        emit DocumentRevoked(docId, reasonHash, educator);
    }

    function isDocumentRevoked(bytes32 docId) external view returns (bool) {
        return _revokedDocuments[docId];
    }

    /// @notice The EIP-712 domain separator, for off-chain signers and tests.
    function domainSeparator() external view returns (bytes32) {
        return _domainSeparatorV4();
    }

    // ---- ERC721 overrides ----
    /// @dev data:application/json;base64 with a name and hex hashes only.
    function tokenURI(uint256 tokenId) public view override returns (string memory) {
        _requireBadge(tokenId);
        Badge storage b = _badges[tokenId];
        bytes memory head = abi.encodePacked(
            '{"name":"SmartQuiz Concept Badge #', Strings.toString(tokenId),
            '","doc_id":"', Strings.toHexString(uint256(b.docId), 32),
            '","concept_hash":"', Strings.toHexString(uint256(b.conceptHash), 32)
        );
        bytes memory tail = abi.encodePacked(
            '","evidence_hash":"', Strings.toHexString(uint256(b.evidenceHash), 32),
            '","revoked":', b.revoked ? "true" : "false", "}"
        );
        return string.concat("data:application/json;base64,", Base64.encode(bytes.concat(head, tail)));
    }

    function supportsInterface(bytes4 interfaceId) public view override returns (bool) {
        return interfaceId == ERC5192_INTERFACE_ID || super.supportsInterface(interfaceId);
    }

    /// @dev Soulbound: minting (from == 0) is the only allowed update; transfers and burns revert.
    function _update(address to, uint256 tokenId, address auth) internal override returns (address) {
        if (_ownerOf(tokenId) != address(0)) revert Soulbound();
        return super._update(to, tokenId, auth);
    }

    /// @dev Approvals could never be used, so they revert too.
    function approve(address, uint256) public pure override {
        revert Soulbound();
    }

    function setApprovalForAll(address, bool) public pure override {
        revert Soulbound();
    }

    // ---- internal ----
    function _requireBadge(uint256 tokenId) private view {
        if (_ownerOf(tokenId) == address(0)) revert UnknownToken(tokenId);
    }

    function _educatorSigner(bytes32 structHash, bytes calldata sig) private view returns (address signer) {
        signer = ECDSA.recover(_hashTypedDataV4(structHash), sig);
        if (!_educators[signer]) revert NotEducator(signer);
    }
}
