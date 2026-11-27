import { expect } from "chai";
import { ethers } from "hardhat";
import { loadFixture } from "@nomicfoundation/hardhat-toolbox/network-helpers";
import type { Signer } from "ethers";
import fs from "fs";
import path from "path";

// Written by api/scripts/credentials_fixture.py from app/chain/credentials.py + merkle.py (SPEC 9.8 and 9.9).
type Attempt = { quiz_id: string; answers: unknown[]; score: number; total: number; grades: unknown[]; salt: string };
type Fixture = {
  chain_id: number;
  deployer_key: string;
  deployer: string;
  registry_address: string;
  credentials_address: string;
  educator: string;
  stranger: string;
  batch_uuid: string;
  batch_id: string;
  root: string;
  attempts: { attempt: Attempt; attempt_hash: string; leaf: string; proof: string[] }[];
  doc_uuid: string;
  doc_id: string;
  fact_root: string;
  fact_count: number;
  concept: string;
  concept_hash: string;
  evidence_hash: string;
  badge_token_id: number;
  badge_reason_hash: string;
  doc_reason_hash: string;
  sigs: { cosign: string; revoke_badge: string; revoke_document: string; cosign_by_stranger: string };
};
const fx: Fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "credentials.json"), "utf-8"));

const idOf = (s: string) => ethers.keccak256(ethers.toUtf8Bytes(s));
const coder = ethers.AbiCoder.defaultAbiCoder();
const resultLeaf = (attemptHash: string) =>
  ethers.keccak256(ethers.keccak256(coder.encode(["bytes32"], [attemptHash])));

/** SPEC section 8 canonical JSON: sorted keys, no spaces, non-ASCII kept as UTF-8 (= Python ensure_ascii=False). */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    return `{${Object.keys(obj).sort().map((k) => `${JSON.stringify(k)}:${canonical(obj[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

const TYPES = {
  CoSign: [
    { name: "docId", type: "bytes32" },
    { name: "factRoot", type: "bytes32" },
  ],
  RevokeBadge: [
    { name: "tokenId", type: "uint256" },
    { name: "reasonHash", type: "bytes32" },
  ],
  RevokeDocument: [
    { name: "docId", type: "bytes32" },
    { name: "reasonHash", type: "bytes32" },
  ],
};

async function deploy() {
  const [owner, educator, learner, other, stranger] = await ethers.getSigners();
  const registry = await (await ethers.getContractFactory("SmartQuizRegistry")).deploy(owner.address);
  const creds = await (await ethers.getContractFactory("SmartQuizCredentials")).deploy(
    owner.address,
    await registry.getAddress(),
  );
  await creds.addEducator(educator.address);
  const { chainId } = await ethers.provider.getNetwork();
  const domain = {
    name: "SmartQuizCredentials",
    version: "1",
    chainId,
    verifyingContract: await creds.getAddress(),
  };
  const sign = (s: Signer, primary: keyof typeof TYPES, msg: Record<string, unknown>) =>
    s.signTypedData(domain, { [primary]: TYPES[primary] }, msg);
  return { registry, creds, owner, educator, learner, other, stranger, sign };
}

const docId = idOf("11111111-1111-4111-8111-111111111111");
const factRoot = idOf("fact root");
const conceptHash = idOf("11111111-1111-4111-8111-111111111111|Paging");
const evidenceHash = idOf("evidence");
const reasonHash = idOf("reason");
const batchId = idOf("33333333-3333-4333-8333-333333333333");

async function deployWithBadge() {
  const ctx = await deploy();
  await ctx.creds.mintBadge(ctx.learner.address, docId, conceptHash, evidenceHash);
  return ctx;
}

describe("SmartQuizCredentials", () => {
  describe("setup and educators", () => {
    it("sets owner, registry, name and symbol", async () => {
      const { creds, registry, owner } = await loadFixture(deploy);
      expect(await creds.owner()).to.equal(owner.address);
      expect(await creds.registry()).to.equal(await registry.getAddress());
      expect(await creds.name()).to.equal("SmartQuiz Concept Badge");
      expect(await creds.symbol()).to.equal("SQB");
    });

    it("owner adds and removes educators, with events", async () => {
      const { creds, other } = await loadFixture(deploy);
      expect(await creds.isEducator(other.address)).to.equal(false);
      await expect(creds.addEducator(other.address)).to.emit(creds, "EducatorAdded").withArgs(other.address);
      expect(await creds.isEducator(other.address)).to.equal(true);
      await expect(creds.removeEducator(other.address)).to.emit(creds, "EducatorRemoved").withArgs(other.address);
      expect(await creds.isEducator(other.address)).to.equal(false);
    });

    it("only the owner can add or remove educators", async () => {
      const { creds, educator, other } = await loadFixture(deploy);
      await expect(creds.connect(other).addEducator(other.address))
        .to.be.revertedWithCustomError(creds, "OwnableUnauthorizedAccount")
        .withArgs(other.address);
      await expect(creds.connect(educator).removeEducator(educator.address))
        .to.be.revertedWithCustomError(creds, "OwnableUnauthorizedAccount")
        .withArgs(educator.address);
    });

    it("typehashes match the SPEC 9.8 type strings", async () => {
      const { creds } = await loadFixture(deploy);
      expect(await creds.COSIGN_TYPEHASH()).to.equal(idOf("CoSign(bytes32 docId,bytes32 factRoot)"));
      expect(await creds.REVOKE_BADGE_TYPEHASH()).to.equal(idOf("RevokeBadge(uint256 tokenId,bytes32 reasonHash)"));
      expect(await creds.REVOKE_DOCUMENT_TYPEHASH()).to.equal(idOf("RevokeDocument(bytes32 docId,bytes32 reasonHash)"));
    });

    it("has no payable entry point", async () => {
      const { creds, owner } = await loadFixture(deploy);
      await expect(owner.sendTransaction({ to: await creds.getAddress(), value: 1n })).to.be.reverted;
      for (const f of creds.interface.fragments) {
        if (f.type === "function" || f.type === "constructor") expect((f as unknown as { payable: boolean }).payable).to.equal(false);
      }
    });
  });

  describe("result batches", () => {
    const leaves = ["a", "b", "c"].map((s) => resultLeaf(idOf(s)));
    const pair = (a: string, b: string) => ethers.keccak256(ethers.concat(a < b ? [a, b] : [b, a]));
    const root = pair(pair(leaves[0], leaves[1]), leaves[2]);

    it("anchors a batch, emits ResultsAnchored and returns it from getBatch", async () => {
      const { creds } = await loadFixture(deploy);
      await expect(creds.anchorResults(batchId, root, 3)).to.emit(creds, "ResultsAnchored").withArgs(batchId, root, 3);
      const [r, count, at] = await creds.getBatch(batchId);
      expect(r).to.equal(root);
      expect(count).to.equal(3n);
      expect(at).to.be.greaterThan(0n);
    });

    it("reverts a duplicate batch and non-owner anchoring", async () => {
      const { creds, other } = await loadFixture(deploy);
      await creds.anchorResults(batchId, root, 3);
      await expect(creds.anchorResults(batchId, root, 3))
        .to.be.revertedWithCustomError(creds, "BatchExists")
        .withArgs(batchId);
      await expect(creds.connect(other).anchorResults(idOf("x"), root, 1)).to.be.revertedWithCustomError(
        creds,
        "OwnableUnauthorizedAccount",
      );
    });

    it("verifyResult is true for members, false for a non-member or a wrong proof", async () => {
      const { creds } = await loadFixture(deploy);
      await creds.anchorResults(batchId, root, 3);
      expect(await creds.verifyResult(batchId, leaves[0], [leaves[1], leaves[2]])).to.equal(true);
      expect(await creds.verifyResult(batchId, leaves[2], [pair(leaves[0], leaves[1])])).to.equal(true);
      expect(await creds.verifyResult(batchId, resultLeaf(idOf("d")), [leaves[1], leaves[2]])).to.equal(false);
      expect(await creds.verifyResult(batchId, leaves[0], [leaves[2]])).to.equal(false);
    });

    it("verifyResult reverts UnknownBatch; getBatch of an unknown batch is all zero", async () => {
      const { creds } = await loadFixture(deploy);
      await expect(creds.verifyResult(batchId, leaves[0], []))
        .to.be.revertedWithCustomError(creds, "UnknownBatch")
        .withArgs(batchId);
      const [r, count, at] = await creds.getBatch(batchId);
      expect([r, count, at]).to.deep.equal([ethers.ZeroHash, 0n, 0n]);
    });
  });

  describe("soulbound badges", () => {
    it("mints token 1, emits BadgeMinted and Locked, getBadge returns it", async () => {
      const { creds, learner } = await loadFixture(deploy);
      const tx = creds.mintBadge(learner.address, docId, conceptHash, evidenceHash);
      await expect(tx).to.emit(creds, "Locked").withArgs(1n);
      await expect(tx)
        .to.emit(creds, "BadgeMinted")
        .withArgs(1n, learner.address, docId, conceptHash, evidenceHash);
      expect(await creds.ownerOf(1)).to.equal(learner.address);
      expect(await creds.balanceOf(learner.address)).to.equal(1n);
      const [d, c, e, issuedAt, revoked] = await creds.getBadge(1);
      expect([d, c, e, revoked]).to.deep.equal([docId, conceptHash, evidenceHash, false]);
      expect(issuedAt).to.be.greaterThan(0n);
      await creds.mintBadge(learner.address, docId, conceptHash, evidenceHash);
      expect(await creds.ownerOf(2)).to.equal(learner.address);
    });

    it("only the owner mints", async () => {
      const { creds, learner, educator } = await loadFixture(deploy);
      await expect(
        creds.connect(educator).mintBadge(learner.address, docId, conceptHash, evidenceHash),
      ).to.be.revertedWithCustomError(creds, "OwnableUnauthorizedAccount");
    });

    it("locked() is true for a badge and reverts UnknownToken otherwise; getBadge too", async () => {
      const { creds } = await loadFixture(deployWithBadge);
      expect(await creds.locked(1)).to.equal(true);
      await expect(creds.locked(2)).to.be.revertedWithCustomError(creds, "UnknownToken").withArgs(2n);
      await expect(creds.getBadge(2)).to.be.revertedWithCustomError(creds, "UnknownToken").withArgs(2n);
      await expect(creds.tokenURI(2)).to.be.revertedWithCustomError(creds, "UnknownToken").withArgs(2n);
    });

    it("supports ERC-5192 (0xb45a3c0e), ERC-721 and ERC-165", async () => {
      const { creds } = await loadFixture(deploy);
      expect(await creds.supportsInterface("0xb45a3c0e")).to.equal(true);
      expect(await creds.supportsInterface("0x80ac58cd")).to.equal(true);
      expect(await creds.supportsInterface("0x5b5e139f")).to.equal(true); // metadata
      expect(await creds.supportsInterface("0x01ffc9a7")).to.equal(true);
      expect(await creds.supportsInterface("0xffffffff")).to.equal(false);
    });

    it("every transfer and approval path reverts Soulbound, even for the holder", async () => {
      const { creds, learner, other, owner } = await loadFixture(deployWithBadge);
      const asHolder = creds.connect(learner);
      await expect(asHolder.transferFrom(learner.address, other.address, 1)).to.be.revertedWithCustomError(
        creds,
        "Soulbound",
      );
      await expect(
        asHolder["safeTransferFrom(address,address,uint256)"](learner.address, other.address, 1),
      ).to.be.revertedWithCustomError(creds, "Soulbound");
      await expect(
        asHolder["safeTransferFrom(address,address,uint256,bytes)"](learner.address, other.address, 1, "0x"),
      ).to.be.revertedWithCustomError(creds, "Soulbound");
      await expect(asHolder.approve(other.address, 1)).to.be.revertedWithCustomError(creds, "Soulbound");
      await expect(asHolder.setApprovalForAll(other.address, true)).to.be.revertedWithCustomError(creds, "Soulbound");
      // Not even the contract owner (issuer) can move it.
      await expect(creds.connect(owner).transferFrom(learner.address, owner.address, 1)).to.be.revertedWithCustomError(
        creds,
        "Soulbound",
      );
      expect(await creds.ownerOf(1)).to.equal(learner.address);
      expect(await creds.getApproved(1)).to.equal(ethers.ZeroAddress);
    });

    it("tokenURI is base64 JSON with a name and hex hashes only", async () => {
      const { creds } = await loadFixture(deployWithBadge);
      const uri = await creds.tokenURI(1);
      const prefix = "data:application/json;base64,";
      expect(uri.startsWith(prefix)).to.equal(true);
      const json = JSON.parse(Buffer.from(uri.slice(prefix.length), "base64").toString("utf-8"));
      expect(json).to.deep.equal({
        name: "SmartQuiz Concept Badge #1",
        doc_id: docId,
        concept_hash: conceptHash,
        evidence_hash: evidenceHash,
        revoked: false,
      });
      // No text beyond the fixed name: every other value is 0x + 64 hex or a boolean.
      for (const [k, v] of Object.entries(json)) {
        if (k === "name" || k === "revoked") continue;
        expect(v).to.match(/^0x[0-9a-f]{64}$/);
      }
      expect(uri).to.not.include("Paging");
    });
  });

  describe("revokeBadge (EIP-712 RevokeBadge)", () => {
    it("revokes with a valid educator signature; badge kept and marked; tokenURI shows revoked", async () => {
      const { creds, educator, learner, sign } = await loadFixture(deployWithBadge);
      const sig = await sign(educator, "RevokeBadge", { tokenId: 1n, reasonHash });
      await expect(creds.revokeBadge(1, reasonHash, sig))
        .to.emit(creds, "BadgeRevoked")
        .withArgs(1n, reasonHash, educator.address);
      expect((await creds.getBadge(1))[4]).to.equal(true);
      expect(await creds.ownerOf(1)).to.equal(learner.address);
      const json = JSON.parse(Buffer.from((await creds.tokenURI(1)).split(",")[1], "base64").toString("utf-8"));
      expect(json.revoked).to.equal(true);
    });

    it("rejects a non-educator signature with NotEducator(signer)", async () => {
      const { creds, other, sign } = await loadFixture(deployWithBadge);
      const sig = await sign(other, "RevokeBadge", { tokenId: 1n, reasonHash });
      await expect(creds.revokeBadge(1, reasonHash, sig))
        .to.be.revertedWithCustomError(creds, "NotEducator")
        .withArgs(other.address);
    });

    it("a signature for other values recovers another address and is rejected", async () => {
      const { creds, educator, sign } = await loadFixture(deployWithBadge);
      const sig = await sign(educator, "RevokeBadge", { tokenId: 1n, reasonHash: idOf("other reason") });
      await expect(creds.revokeBadge(1, reasonHash, sig)).to.be.revertedWithCustomError(creds, "NotEducator");
    });

    it("a removed educator's signature is rejected", async () => {
      const { creds, educator, sign } = await loadFixture(deployWithBadge);
      const sig = await sign(educator, "RevokeBadge", { tokenId: 1n, reasonHash });
      await creds.removeEducator(educator.address);
      await expect(creds.revokeBadge(1, reasonHash, sig))
        .to.be.revertedWithCustomError(creds, "NotEducator")
        .withArgs(educator.address);
    });

    it("replaying the same signature on a revoked badge reverts AlreadyRevoked", async () => {
      const { creds, educator, sign } = await loadFixture(deployWithBadge);
      const sig = await sign(educator, "RevokeBadge", { tokenId: 1n, reasonHash });
      await creds.revokeBadge(1, reasonHash, sig);
      await expect(creds.revokeBadge(1, reasonHash, sig)).to.be.revertedWithCustomError(creds, "AlreadyRevoked");
    });

    it("unknown token reverts UnknownToken; only the owner submits", async () => {
      const { creds, educator, sign } = await loadFixture(deployWithBadge);
      const sig = await sign(educator, "RevokeBadge", { tokenId: 9n, reasonHash });
      await expect(creds.revokeBadge(9, reasonHash, sig)).to.be.revertedWithCustomError(creds, "UnknownToken");
      const sig1 = await sign(educator, "RevokeBadge", { tokenId: 1n, reasonHash });
      await expect(creds.connect(educator).revokeBadge(1, reasonHash, sig1)).to.be.revertedWithCustomError(
        creds,
        "OwnableUnauthorizedAccount",
      );
    });
  });

  describe("coSignDocument (EIP-712 CoSign)", () => {
    async function registered() {
      const ctx = await deploy();
      await ctx.registry.registerDocument(docId, factRoot, 12);
      return ctx;
    }

    it("co-signs when factRoot matches the registry; getCoSign returns educator and time", async () => {
      const { creds, educator, sign } = await loadFixture(registered);
      const sig = await sign(educator, "CoSign", { docId, factRoot });
      await expect(creds.coSignDocument(docId, factRoot, sig))
        .to.emit(creds, "DocumentCoSigned")
        .withArgs(docId, factRoot, educator.address);
      const [who, at] = await creds.getCoSign(docId);
      expect(who).to.equal(educator.address);
      expect(at).to.be.greaterThan(0n);
    });

    it("reverts RootMismatch when the root differs from the registry's", async () => {
      const { creds, educator, sign } = await loadFixture(registered);
      const wrong = idOf("another root");
      const sig = await sign(educator, "CoSign", { docId, factRoot: wrong });
      await expect(creds.coSignDocument(docId, wrong, sig))
        .to.be.revertedWithCustomError(creds, "RootMismatch")
        .withArgs(factRoot, wrong);
    });

    it("reverts RootMismatch for an unregistered document, even with root 0", async () => {
      const { creds, educator, sign } = await loadFixture(deploy);
      const sig = await sign(educator, "CoSign", { docId, factRoot });
      await expect(creds.coSignDocument(docId, factRoot, sig)).to.be.revertedWithCustomError(creds, "RootMismatch");
      const zero = await sign(educator, "CoSign", { docId, factRoot: ethers.ZeroHash });
      await expect(creds.coSignDocument(docId, ethers.ZeroHash, zero)).to.be.revertedWithCustomError(
        creds,
        "RootMismatch",
      );
    });

    it("rejects a non-educator signature", async () => {
      const { creds, other, sign } = await loadFixture(registered);
      const sig = await sign(other, "CoSign", { docId, factRoot });
      await expect(creds.coSignDocument(docId, factRoot, sig))
        .to.be.revertedWithCustomError(creds, "NotEducator")
        .withArgs(other.address);
      expect((await creds.getCoSign(docId))[0]).to.equal(ethers.ZeroAddress);
    });

    it("a signature from another domain (contract address) is rejected", async () => {
      const { creds, educator } = await loadFixture(registered);
      const { chainId } = await ethers.provider.getNetwork();
      const foreign = { name: "SmartQuizCredentials", version: "1", chainId, verifyingContract: ethers.ZeroAddress };
      const sig = await educator.signTypedData(foreign, { CoSign: TYPES.CoSign }, { docId, factRoot });
      await expect(creds.coSignDocument(docId, factRoot, sig)).to.be.revertedWithCustomError(creds, "NotEducator");
    });
  });

  describe("revokeDocument (EIP-712 RevokeDocument)", () => {
    it("revokes with an educator signature; replay reverts AlreadyRevoked", async () => {
      const { creds, educator, sign } = await loadFixture(deploy);
      expect(await creds.isDocumentRevoked(docId)).to.equal(false);
      const sig = await sign(educator, "RevokeDocument", { docId, reasonHash });
      await expect(creds.revokeDocument(docId, reasonHash, sig))
        .to.emit(creds, "DocumentRevoked")
        .withArgs(docId, reasonHash, educator.address);
      expect(await creds.isDocumentRevoked(docId)).to.equal(true);
      await expect(creds.revokeDocument(docId, reasonHash, sig)).to.be.revertedWithCustomError(creds, "AlreadyRevoked");
    });

    it("rejects a non-educator signature and a CoSign signature reused as RevokeDocument", async () => {
      const { creds, educator, other, sign } = await loadFixture(deploy);
      const bad = await sign(other, "RevokeDocument", { docId, reasonHash });
      await expect(creds.revokeDocument(docId, reasonHash, bad))
        .to.be.revertedWithCustomError(creds, "NotEducator")
        .withArgs(other.address);
      const cosign = await sign(educator, "CoSign", { docId, factRoot: reasonHash });
      await expect(creds.revokeDocument(docId, reasonHash, cosign)).to.be.revertedWithCustomError(creds, "NotEducator");
      expect(await creds.isDocumentRevoked(docId)).to.equal(false);
    });
  });

  describe("Python cross-check (fixtures/credentials.json)", () => {
    // Deploys from the fixture's fresh test-only deployer (nonces 0 and 1), so the address matches the EIP-712
    // domain the Python signatures were made for.
    async function deployFromFixture() {
      const [funder] = await ethers.getSigners();
      const deployer = new ethers.Wallet(fx.deployer_key, ethers.provider);
      await (await funder.sendTransaction({ to: deployer.address, value: ethers.parseEther("10") })).wait();
      const registry = await (await ethers.getContractFactory("SmartQuizRegistry", deployer)).deploy(deployer.address);
      const creds = await (await ethers.getContractFactory("SmartQuizCredentials", deployer)).deploy(
        deployer.address,
        await registry.getAddress(),
      );
      await creds.addEducator(fx.educator);
      await registry.registerDocument(fx.doc_id, fx.fact_root, fx.fact_count);
      return { registry, creds, deployer };
    }

    it("deploys at the addresses Python predicted, on the fixture chain id", async () => {
      const { registry, creds, deployer } = await loadFixture(deployFromFixture);
      expect(deployer.address).to.equal(fx.deployer);
      expect(await registry.getAddress()).to.equal(fx.registry_address);
      expect(await creds.getAddress()).to.equal(fx.credentials_address);
      expect((await ethers.provider.getNetwork()).chainId).to.equal(BigInt(fx.chain_id));
    });

    it("Python attempt hashes, leaves, batch id, concept and evidence hashes match TypeScript", async () => {
      expect(fx.attempts).to.have.length(5);
      for (const a of fx.attempts) {
        expect(ethers.keccak256(ethers.toUtf8Bytes(canonical(a.attempt)))).to.equal(a.attempt_hash);
        expect(resultLeaf(a.attempt_hash)).to.equal(a.leaf);
      }
      expect(idOf(fx.batch_uuid)).to.equal(fx.batch_id);
      expect(idOf(fx.doc_uuid)).to.equal(fx.doc_id);
      expect(idOf(`${fx.doc_uuid}|${fx.concept}`)).to.equal(fx.concept_hash);
      const sorted = fx.attempts.slice(0, 3).map((a) => a.attempt_hash).sort();
      expect(ethers.keccak256(ethers.concat(sorted))).to.equal(fx.evidence_hash);
    });

    it("anchors the Python root and verifies every Python proof on chain", async () => {
      const { creds } = await loadFixture(deployFromFixture);
      await creds.anchorResults(fx.batch_id, fx.root, fx.attempts.length);
      for (const [i, a] of fx.attempts.entries()) {
        expect(await creds.verifyResult(fx.batch_id, a.leaf, a.proof), `attempt ${i}`).to.equal(true);
      }
      // A tampered attempt (score + 1) gives another hash and fails.
      const a0 = fx.attempts[0];
      const tampered = ethers.keccak256(ethers.toUtf8Bytes(canonical({ ...a0.attempt, score: a0.attempt.score + 1 })));
      expect(await creds.verifyResult(fx.batch_id, resultLeaf(tampered), a0.proof)).to.equal(false);
    });

    it("accepts the Python EIP-712 CoSign, RevokeBadge and RevokeDocument signatures", async () => {
      const { creds } = await loadFixture(deployFromFixture);
      await expect(creds.coSignDocument(fx.doc_id, fx.fact_root, fx.sigs.cosign))
        .to.emit(creds, "DocumentCoSigned")
        .withArgs(fx.doc_id, fx.fact_root, fx.educator);

      const learner = ethers.Wallet.createRandom().address;
      await creds.mintBadge(learner, fx.doc_id, fx.concept_hash, fx.evidence_hash);
      expect((await creds.getBadge(fx.badge_token_id))[1]).to.equal(fx.concept_hash);
      await expect(creds.revokeBadge(fx.badge_token_id, fx.badge_reason_hash, fx.sigs.revoke_badge))
        .to.emit(creds, "BadgeRevoked")
        .withArgs(fx.badge_token_id, fx.badge_reason_hash, fx.educator);

      await expect(creds.revokeDocument(fx.doc_id, fx.doc_reason_hash, fx.sigs.revoke_document))
        .to.emit(creds, "DocumentRevoked")
        .withArgs(fx.doc_id, fx.doc_reason_hash, fx.educator);
    });

    it("rejects the Python stranger's signature with NotEducator(stranger)", async () => {
      const { creds } = await loadFixture(deployFromFixture);
      await expect(creds.coSignDocument(fx.doc_id, fx.fact_root, fx.sigs.cosign_by_stranger))
        .to.be.revertedWithCustomError(creds, "NotEducator")
        .withArgs(fx.stranger);
    });
  });
});
