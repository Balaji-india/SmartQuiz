import { expect } from "chai";
import { ethers } from "hardhat";

describe("Placeholder", () => {
  it("deploys with the given owner", async () => {
    const [signer] = await ethers.getSigners();
    const factory = await ethers.getContractFactory("Placeholder");
    const contract = await factory.deploy(signer.address);
    expect(await contract.owner()).to.equal(signer.address);
  });
});
