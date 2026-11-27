// Deploys SmartQuizCredentials (SPEC 9.8) next to the unchanged SmartQuizRegistry:
//   owner = issuer (ISSUER_PRIVATE_KEY), registry = REGISTRY_ADDRESS, then addEducator(address of EDUCATOR_PRIVATE_KEY).
//   The issuer sends both transactions; the educator wallet only signs EIP-712 messages and needs no POL.
//   amoy:      prints the issuer balance first and stops if it cannot cover both txs; uses amoyFees() (tip >= 30 gwei);
//              writes CREDENTIALS_ADDRESS into ../.env (that line only).
//   localhost: never touches .env; sends the issuer 100 test ETH from account 0 and, if REGISTRY_ADDRESS has no code
//              on this chain, deploys a fresh registry first (owner = issuer).
// Linux:   npx hardhat run scripts/deploy-credentials.ts --network <amoy|localhost>
// Windows: npx.cmd hardhat run scripts/deploy-credentials.ts --network <amoy|localhost>
import { ethers, network } from "hardhat";
import { amoyFees, formatFees, type Fees } from "./fees";
import { addressOfEnvKey, walletOfEnvKey, writeEnvLine } from "./env";

const isAmoy = network.name === "amoy";

async function hasCode(address: string | undefined): Promise<boolean> {
  return !!address && ethers.isAddress(address) && (await ethers.provider.getCode(address)) !== "0x";
}

async function main() {
  const issuer = walletOfEnvKey("ISSUER_PRIVATE_KEY");
  const educator = addressOfEnvKey("EDUCATOR_PRIVATE_KEY");
  if (educator === issuer.address) throw new Error("EDUCATOR_PRIVATE_KEY must be a different wallet from the issuer");
  const { chainId } = await ethers.provider.getNetwork();
  console.log(`network ${network.name} (chain id ${chainId})`);
  console.log(`issuer   ${issuer.address}`);
  console.log(`educator ${educator}`);

  if (!isAmoy) {
    const [funder] = await ethers.getSigners();
    await (await funder.sendTransaction({ to: issuer.address, value: ethers.parseEther("100") })).wait();
    console.log("sent 100 test ETH to the issuer");
  }

  let registryAddress = process.env.REGISTRY_ADDRESS?.trim();
  if (!(await hasCode(registryAddress))) {
    if (isAmoy) throw new Error(`REGISTRY_ADDRESS ${registryAddress || "(empty)"} has no contract on Amoy`);
    const registry = await (await ethers.getContractFactory("SmartQuizRegistry", issuer)).deploy(issuer.address);
    await registry.waitForDeployment();
    registryAddress = await registry.getAddress();
    console.log(`REGISTRY_ADDRESS has no code here; deployed a local SmartQuizRegistry at ${registryAddress}`);
  }
  const registry = await ethers.getContractAt("SmartQuizRegistry", registryAddress!);
  const registryOwner = await registry.owner();
  if (registryOwner !== issuer.address) console.warn(`warning: registry owner is ${registryOwner}, not the issuer`);
  console.log(`registry ${registryAddress}`);

  const factory = await ethers.getContractFactory("SmartQuizCredentials", issuer);
  let fees: Fees | undefined;
  if (isAmoy) {
    fees = await amoyFees(ethers.provider);
    console.log(formatFees(fees));
    const deployGas = await ethers.provider.estimateGas({
      ...(await factory.getDeployTransaction(issuer.address, registryAddress!)),
      from: issuer.address,
    });
    const addEducatorGas = 60_000n; // measured ~48k on Hardhat; generous
    const need = ((deployGas * 12n) / 10n + addEducatorGas) * fees.maxFeePerGas;
    const balance = await ethers.provider.getBalance(issuer.address);
    console.log(`issuer balance ${ethers.formatEther(balance)} POL; need at most ${ethers.formatEther(need)} POL (deploy gas ~${deployGas})`);
    if (balance < need) {
      console.error("issuer balance too low: top up the issuer from the Amoy faucet, then rerun. Nothing was sent.");
      process.exitCode = 2;
      return;
    }
  }

  const creds = await factory.deploy(issuer.address, registryAddress!, ...(fees ? [fees] : []));
  await creds.waitForDeployment();
  const address = await creds.getAddress();
  console.log(`SmartQuizCredentials deployed on ${network.name} at ${address} (owner ${issuer.address})`);
  const deployTx = creds.deploymentTransaction();

  const addTx = isAmoy
    ? await creds.addEducator(educator, await amoyFees(ethers.provider))
    : await creds.addEducator(educator);
  await addTx.wait();
  console.log(`addEducator(${educator}): isEducator = ${await creds.isEducator(educator)}`);

  if (isAmoy) {
    writeEnvLine("CREDENTIALS_ADDRESS", address);
    console.log("wrote CREDENTIALS_ADDRESS to .env");
    if (deployTx) console.log(`deploy      https://amoy.polygonscan.com/tx/${deployTx.hash}`);
    console.log(`addEducator https://amoy.polygonscan.com/tx/${addTx.hash}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
