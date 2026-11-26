// Moves SmartQuizRegistry ownership from the current issuer (ISSUER_PRIVATE_KEY in ../.env) to NEW_OWNER.
// Run it with the OLD issuer key still in .env; switch ISSUER_PRIVATE_KEY to the new key only after it succeeds.
// Never touches .env.
// Linux:   NEW_OWNER=0x... npx hardhat run scripts/transfer-owner.ts --network amoy
// Windows: $env:NEW_OWNER="0x..."; npx.cmd hardhat run scripts/transfer-owner.ts --network amoy
import { ethers, network } from "hardhat";

async function main() {
  const registryAddress = process.env.REGISTRY_ADDRESS?.trim();
  const newOwnerRaw = process.env.NEW_OWNER?.trim();
  if (!registryAddress) throw new Error("REGISTRY_ADDRESS is empty in .env");
  if (!newOwnerRaw || !ethers.isAddress(newOwnerRaw)) throw new Error("Set NEW_OWNER to a valid 0x address");
  const newOwner = ethers.getAddress(newOwnerRaw);

  const [signer] = await ethers.getSigners();
  const registry = await ethers.getContractAt("SmartQuizRegistry", registryAddress, signer);

  const current = await registry.owner();
  console.log(`network ${network.name}, registry ${registryAddress}`);
  console.log(`current owner ${current}, signer ${signer.address}, new owner ${newOwner}`);
  if (current === newOwner) {
    console.log("already owned by NEW_OWNER; nothing to do");
    return;
  }
  if (current !== signer.address) throw new Error("The signer is not the current owner; use the old issuer key");

  // Amoy rejects or strands tips under 25 gwei; Hardhat's defaults can be lower. Use the network's tip with a 25 gwei
  // floor, plus 50%, and the confirmed nonce, so a rerun replaces a stuck earlier attempt instead of queueing behind it.
  const provider = signer.provider!;
  const latest = await provider.getBlock("latest");
  const base = latest?.baseFeePerGas ?? 0n;
  const netTip = BigInt(await provider.send("eth_maxPriorityFeePerGas", []));
  const floor = ethers.parseUnits("25", "gwei");
  const tip = ((netTip > floor ? netTip : floor) * 3n) / 2n;
  const maxFee = base * 2n + tip;
  const nonce = await provider.getTransactionCount(signer.address, "latest");
  console.log(`nonce ${nonce}, tip ${ethers.formatUnits(tip, "gwei")} gwei, max fee ${ethers.formatUnits(maxFee, "gwei")} gwei`);

  const tx = await registry.transferOwnership(newOwner, { nonce, maxPriorityFeePerGas: tip, maxFeePerGas: maxFee });
  console.log(`sent ${tx.hash}`);
  await tx.wait();
  const after = await registry.owner();
  console.log(`owner now ${after}`);
  if (after !== newOwner) throw new Error("owner() did not change");
  if (network.name === "amoy") console.log(`https://amoy.polygonscan.com/tx/${tx.hash}`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
