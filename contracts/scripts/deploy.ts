// Deploys SmartQuizRegistry with the issuer (ISSUER_PRIVATE_KEY's address) as owner. SPEC section 6.
//   amoy:      writes REGISTRY_ADDRESS into ../.env (that line only).
//   localhost: never touches .env; sends the issuer 100 test ETH from account 0.
// Linux:   npx hardhat run scripts/deploy.ts --network <amoy|localhost>
// Windows: npx.cmd hardhat run scripts/deploy.ts --network <amoy|localhost>
import fs from "fs";
import path from "path";
import { ethers, network } from "hardhat";

const ENV_PATH = path.resolve(__dirname, "../../.env");

function issuerAddress(): string {
  const key = process.env.ISSUER_PRIVATE_KEY?.trim();
  if (!key) throw new Error("ISSUER_PRIVATE_KEY is empty in .env");
  return new ethers.Wallet(key.startsWith("0x") ? key : `0x${key}`).address;
}

function writeRegistryAddress(address: string): void {
  const original = fs.readFileSync(ENV_PATH, "utf-8");
  const eol = original.includes("\r\n") ? "\r\n" : "\n";
  const lines = original.split(/\r?\n/);
  let found = false;
  const updated = lines.map((line) => {
    if (/^REGISTRY_ADDRESS=/.test(line)) {
      found = true;
      return `REGISTRY_ADDRESS=${address}`;
    }
    return line;
  });
  if (!found) {
    // Keep a trailing newline at the end of the file.
    if (updated[updated.length - 1] === "") updated.splice(updated.length - 1, 0, `REGISTRY_ADDRESS=${address}`);
    else updated.push(`REGISTRY_ADDRESS=${address}`);
  }
  fs.writeFileSync(ENV_PATH, updated.join(eol), "utf-8");
}

async function main() {
  const owner = issuerAddress();

  if (network.name === "localhost" || network.name === "hardhat") {
    const [funder] = await ethers.getSigners();
    const tx = await funder.sendTransaction({ to: owner, value: ethers.parseEther("100") });
    await tx.wait();
    console.log(`sent 100 test ETH to issuer ${owner}`);
  }

  const registry = await (await ethers.getContractFactory("SmartQuizRegistry")).deploy(owner);
  await registry.waitForDeployment();
  const address = await registry.getAddress();
  console.log(`SmartQuizRegistry deployed on ${network.name} at ${address} (owner ${owner})`);

  if (network.name === "amoy") {
    writeRegistryAddress(address);
    console.log("wrote REGISTRY_ADDRESS to .env");
    const tx = registry.deploymentTransaction();
    if (tx) console.log(`https://amoy.polygonscan.com/tx/${tx.hash}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
