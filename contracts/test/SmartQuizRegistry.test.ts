import { expect } from "chai";
import { ethers } from "hardhat";
import fs from "fs";
import path from "path";

type FixtureFact = { idx: number; text: string; text_hash: string; leaf: string; proof: string[] };
type Fixture = { doc_uuid: string; root: string; facts: FixtureFact[] };

// Written by api/scripts/merkle_fixture.py from app/chain/merkle.py.
const fixture: Fixture = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures", "merkle.json"), "utf-8"),
);

// doc_id / quiz_id on chain = keccak256(utf-8 UUID string), SPEC sections 6 and 8.
const idOf = (uuid: string) => ethers.keccak256(ethers.toUtf8Bytes(uuid));

async function deploy() {
  const [owner, other] = await ethers.getSigners();
  const registry = await (await ethers.getContractFactory("SmartQuizRegistry")).deploy(owner.address);
  return { registry, owner, other };
}

describe("SmartQuizRegistry", () => {
  const docId = idOf("11111111-1111-4111-8111-111111111111");
  const quizId = idOf("22222222-2222-4222-8222-222222222222");
  const root = ethers.keccak256(ethers.toUtf8Bytes("root"));
  const quizHash = ethers.keccak256(ethers.toUtf8Bytes("quiz"));

  it("sets the owner", async () => {
    const { registry, owner } = await deploy();
    expect(await registry.owner()).to.equal(owner.address);
  });

  it("registers a document, emits the event and returns it from getDocument", async () => {
    const { registry } = await deploy();
    await expect(registry.registerDocument(docId, root, 184))
      .to.emit(registry, "DocumentRegistered")
      .withArgs(docId, root, 184);
    const [storedRoot, count, registeredAt] = await registry.getDocument(docId);
    expect(storedRoot).to.equal(root);
    expect(count).to.equal(184n);
    expect(registeredAt).to.be.greaterThan(0n);
  });

  it("reverts a duplicate registration", async () => {
    const { registry } = await deploy();
    await registry.registerDocument(docId, root, 1);
    await expect(registry.registerDocument(docId, root, 1))
      .to.be.revertedWithCustomError(registry, "AlreadyRegistered")
      .withArgs(docId);
  });

  it("only the owner can register or commit", async () => {
    const { registry, other } = await deploy();
    await expect(registry.connect(other).registerDocument(docId, root, 1))
      .to.be.revertedWithCustomError(registry, "OwnableUnauthorizedAccount")
      .withArgs(other.address);
    await registry.registerDocument(docId, root, 1);
    await expect(registry.connect(other).commitQuiz(quizId, docId, quizHash))
      .to.be.revertedWithCustomError(registry, "OwnableUnauthorizedAccount")
      .withArgs(other.address);
  });

  it("commits a quiz, emits the event and returns it from getQuiz", async () => {
    const { registry } = await deploy();
    await registry.registerDocument(docId, root, 1);
    await expect(registry.commitQuiz(quizId, docId, quizHash))
      .to.emit(registry, "QuizCommitted")
      .withArgs(quizId, docId, quizHash);
    const [storedDoc, storedHash, committedAt] = await registry.getQuiz(quizId);
    expect(storedDoc).to.equal(docId);
    expect(storedHash).to.equal(quizHash);
    expect(committedAt).to.be.greaterThan(0n);
  });

  it("reverts a re-commit", async () => {
    const { registry } = await deploy();
    await registry.registerDocument(docId, root, 1);
    await registry.commitQuiz(quizId, docId, quizHash);
    await expect(registry.commitQuiz(quizId, docId, quizHash))
      .to.be.revertedWithCustomError(registry, "AlreadyCommitted")
      .withArgs(quizId);
  });

  it("reverts a commit for an unknown document", async () => {
    const { registry } = await deploy();
    await expect(registry.commitQuiz(quizId, docId, quizHash))
      .to.be.revertedWithCustomError(registry, "UnknownDocument")
      .withArgs(docId);
  });

  it("getters return zeros for unknown ids", async () => {
    const { registry } = await deploy();
    expect(await registry.getDocument(docId)).to.deep.equal([ethers.ZeroHash, 0n, 0n]);
    expect(await registry.getQuiz(quizId)).to.deep.equal([ethers.ZeroHash, ethers.ZeroHash, 0n]);
  });

  describe("Python merkle.py cross-check (fixtures/merkle.json)", () => {
    const fixtureDoc = idOf(fixture.doc_uuid);

    it("has 7 facts, so one leaf is promoted", () => {
      expect(fixture.facts).to.have.length(7);
    });

    it("recomputes text_hash and leaf in Solidity's format", () => {
      const coder = ethers.AbiCoder.defaultAbiCoder();
      for (const f of fixture.facts) {
        expect(ethers.keccak256(ethers.toUtf8Bytes(f.text))).to.equal(f.text_hash);
        const inner = ethers.keccak256(coder.encode(["uint256", "bytes32"], [f.idx, f.text_hash]));
        expect(ethers.keccak256(inner)).to.equal(f.leaf);
      }
    });

    it("verifyFact is true for every Python proof, including the promoted node", async () => {
      const { registry } = await deploy();
      await registry.registerDocument(fixtureDoc, fixture.root, fixture.facts.length);
      for (const f of fixture.facts) {
        expect(await registry.verifyFact(fixtureDoc, f.leaf, f.proof), `idx ${f.idx}`).to.equal(true);
      }
    });

    it("verifyFact is false after changing one byte of a leaf, or for an unknown document", async () => {
      const { registry } = await deploy();
      await registry.registerDocument(fixtureDoc, fixture.root, fixture.facts.length);
      const f = fixture.facts[3];
      const bytes = ethers.getBytes(f.leaf);
      bytes[31] ^= 0x01;
      expect(await registry.verifyFact(fixtureDoc, ethers.hexlify(bytes), f.proof)).to.equal(false);
      expect(await registry.verifyFact(docId, f.leaf, f.proof)).to.equal(false);
    });

    it("verifyFact is false when the text is edited by one word", async () => {
      const { registry } = await deploy();
      await registry.registerDocument(fixtureDoc, fixture.root, fixture.facts.length);
      const f = fixture.facts[0];
      const tampered = f.text.replace("fixed", "variable");
      const coder = ethers.AbiCoder.defaultAbiCoder();
      const th = ethers.keccak256(ethers.toUtf8Bytes(tampered));
      const leaf = ethers.keccak256(ethers.keccak256(coder.encode(["uint256", "bytes32"], [f.idx, th])));
      expect(await registry.verifyFact(fixtureDoc, leaf, f.proof)).to.equal(false);
    });
  });
});
