// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {MerkleProof} from "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";

/// @title SmartQuizRegistry
/// @notice Proof of Grounding: stores each document's fact Merkle root and each quiz's hash.
/// Only hashes are stored. One issuer wallet (the owner) signs every transaction.
contract SmartQuizRegistry is Ownable {
    struct Document {
        bytes32 factRoot;
        uint32 factCount;
        uint64 registeredAt;
    }

    struct Quiz {
        bytes32 docId;
        bytes32 quizHash;
        uint64 committedAt;
    }

    mapping(bytes32 => Document) private _documents;
    mapping(bytes32 => Quiz) private _quizzes;

    event DocumentRegistered(bytes32 indexed docId, bytes32 factRoot, uint32 factCount);
    event QuizCommitted(bytes32 indexed quizId, bytes32 indexed docId, bytes32 quizHash);

    error UnknownDocument(bytes32 docId);
    error AlreadyRegistered(bytes32 docId);
    error AlreadyCommitted(bytes32 quizId);

    constructor(address initialOwner) Ownable(initialOwner) {}

    function registerDocument(bytes32 docId, bytes32 factRoot, uint32 factCount) external onlyOwner {
        if (_documents[docId].registeredAt != 0) revert AlreadyRegistered(docId);
        _documents[docId] = Document(factRoot, factCount, uint64(block.timestamp));
        emit DocumentRegistered(docId, factRoot, factCount);
    }

    function commitQuiz(bytes32 quizId, bytes32 docId, bytes32 quizHash) external onlyOwner {
        if (_quizzes[quizId].committedAt != 0) revert AlreadyCommitted(quizId);
        if (_documents[docId].registeredAt == 0) revert UnknownDocument(docId);
        _quizzes[quizId] = Quiz(docId, quizHash, uint64(block.timestamp));
        emit QuizCommitted(quizId, docId, quizHash);
    }

    /// @notice True if `leaf` is in the registered fact tree of `docId`. False for an unknown document.
    function verifyFact(bytes32 docId, bytes32 leaf, bytes32[] calldata proof) external view returns (bool) {
        Document storage d = _documents[docId];
        if (d.registeredAt == 0) return false;
        return MerkleProof.verifyCalldata(proof, d.factRoot, leaf);
    }

    function getDocument(bytes32 docId)
        external
        view
        returns (bytes32 factRoot, uint32 factCount, uint64 registeredAt)
    {
        Document storage d = _documents[docId];
        return (d.factRoot, d.factCount, d.registeredAt);
    }

    function getQuiz(bytes32 quizId) external view returns (bytes32 docId, bytes32 quizHash, uint64 committedAt) {
        Quiz storage q = _quizzes[quizId];
        return (q.docId, q.quizHash, q.committedAt);
    }
}
