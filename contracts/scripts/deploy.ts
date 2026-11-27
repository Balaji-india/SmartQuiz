// Deploys SmartQuizRegistry with the issuer (ISSUER_PRIVATE_KEY's address) as owner. SPEC section 6.
//   amoy:      writes REGISTRY_ADDRESS into ../.env (that line only).
//   localhost: never touches .env; sends the issuer 100 test ETH from account 0.
// Linux:   npx hardhat run scripts/deploy.ts --network <amoy|localhost>
// Windows: npx.cmd hardhat run scripts/deploy.ts --network <amoy|localhost>
import { ethers, network } from "hardhat";
import { amoyFees, formatFees } from "./fees";
import { addressOfEnvKey, writeEnvLine } from "./env";

async function main() {
  const owner = addressOfEnvKey("ISSUER_PRIVATE_KEY");

  if (network.name === "localhost" || network.name === "hardhat") {
    const [funder] = await ethers.getSigners();
    const tx = await funder.sendTransaction({ to: owner, value: ethers.parseEther("100") });
    await tx.wait();
    console.log(`sent 100 test ETH to issuer ${owner}`);
  }

  const factory = await ethers.getContractFactory("SmartQuizRegistry");
  let registry;
  if (network.name === "amoy") {
    const fees = await amoyFees(ethers.provider);
    console.log(formatFees(fees));
    registry = await factory.deploy(owner, fees);
  } else {
    registry = await factory.deploy(owner);
  }
  await registry.waitForDeployment();
  const address = await registry.getAddress();
  console.log(`SmartQuizRegistry deployed on ${network.name} at ${address} (owner ${owner})`);

  if (network.name === "amoy") {
    writeEnvLine("REGISTRY_ADDRESS", address);
    console.log("wrote REGISTRY_ADDRESS to .env");
    const tx = registry.deploymentTransaction();
    if (tx) console.log(`https://amoy.polygonscan.com/tx/${tx.hash}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
