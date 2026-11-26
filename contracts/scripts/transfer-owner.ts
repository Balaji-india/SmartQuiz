// Moves SmartQuizRegistry ownership from the current issuer (ISSUER_PRIVATE_KEY in ../.env) to NEW_OWNER.
// Run it with the OLD issuer key still in .env; switch ISSUER_PRIVATE_KEY to the new key only after it succeeds.
// Ownable is single-step, so a wrong NEW_OWNER loses the registry for good: NEW_OWNER must be checksummed
// (mixed case, as MetaMask shows it) and CONFIRM=yes must be set. Never touches .env.
// Linux:   NEW_OWNER=0x... CONFIRM=yes npx hardhat run scripts/transfer-owner.ts --network amoy
// Windows: $env:NEW_OWNER="0x..."; $env:CONFIRM="yes"; npx.cmd hardhat run scripts/transfer-owner.ts --network amoy
import { ethers, network } from "hardhat";
import { amoyFees, bumped, formatFees } from "./fees";

const WAIT_MS = 180_000;

async function main() {
  const registryAddress = process.env.REGISTRY_ADDRESS?.trim();
  const newOwnerRaw = process.env.NEW_OWNER?.trim();
  if (!registryAddress) throw new Error("REGISTRY_ADDRESS is empty in .env");
  if (!newOwnerRaw || !ethers.isAddress(newOwnerRaw) || ethers.getAddress(newOwnerRaw) !== newOwnerRaw) {
    throw new Error("Set NEW_OWNER to a checksummed (mixed-case) 0x address, exactly as the wallet shows it");
  }
  const newOwner = newOwnerRaw;

  const [signer] = await ethers.getSigners();
  if (!signer) throw new Error("ISSUER_PRIVATE_KEY is empty in .env");
  const provider = signer.provider!;
  const registry = await ethers.getContractAt("SmartQuizRegistry", registryAddress, signer);

  const current = await registry.owner();
  console.log(`network ${network.name}, registry ${registryAddress}`);
  console.log(`current owner ${current}, signer ${signer.address}, new owner ${newOwner}`);
  if (current === newOwner) {
    console.log("already owned by NEW_OWNER; nothing to do");
    return;
  }
  if (current !== signer.address) throw new Error("The signer is not the current owner; use the old issuer key");
  if ((await provider.getCode(newOwner)) !== "0x") throw new Error("NEW_OWNER is a contract, not a wallet");
  if (process.env.CONFIRM !== "yes") throw new Error("Check the new owner above, then rerun with CONFIRM=yes");

  // Use the confirmed nonce. If an earlier attempt is still pending at that nonce, outbid it by 12.5% on both
  // fees, which nodes require before they accept a replacement.
  const nonce = await provider.getTransactionCount(signer.address, "latest");
  const pendingNonce = await provider.getTransactionCount(signer.address, "pending");
  let fees = await amoyFees(ethers.provider);
  if (pendingNonce > nonce) {
    const block = await provider.send("eth_getBlockByNumber", ["pending", true]).catch(() => null);
    const stuck = (block?.transactions ?? []).find(
      (t: { from?: string; nonce?: string }) =>
        t.from?.toLowerCase() === signer.address.toLowerCase() && BigInt(t.nonce ?? -1) === BigInt(nonce),
    );
    const override = process.env.TIP_GWEI ? ethers.parseUnits(process.env.TIP_GWEI, "gwei") : null;
    if (stuck?.maxPriorityFeePerGas && stuck?.maxFeePerGas) {
      fees = bumped(fees, { maxPriorityFeePerGas: BigInt(stuck.maxPriorityFeePerGas), maxFeePerGas: BigInt(stuck.maxFeePerGas) });
    } else if (override) {
      // Never below the floor; the max fee keeps 2 x base on top of the tip.
      const tip = override > fees.maxPriorityFeePerGas ? override : fees.maxPriorityFeePerGas;
      fees = { maxPriorityFeePerGas: tip, maxFeePerGas: fees.maxFeePerGas - fees.maxPriorityFeePerGas + tip };
    } else {
      throw new Error(
        `nonce ${nonce} has a pending tx whose fees could not be read; rerun with TIP_GWEI set at least 12.5% above ` +
          "the stuck tx's tip (see it on amoy.polygonscan.com)",
      );
    }
    console.log(`replacing the pending tx at nonce ${nonce}`);
  }
  console.log(`nonce ${nonce}, ${formatFees(fees)}`);

  const tx = await registry.transferOwnership(newOwner, { nonce, ...fees });
  console.log(`sent ${tx.hash}`);
  let receipt;
  try {
    receipt = await tx.wait(1, WAIT_MS);
  } catch (err) {
    throw new Error(
      `not mined within ${WAIT_MS / 1000}s (tx ${tx.hash}, nonce ${nonce}); rerun to replace it with higher fees. ${err}`,
    );
  }
  if (!receipt || receipt.status !== 1) throw new Error(`transaction ${tx.hash} failed`);
  const after = await registry.owner();
  console.log(`owner now ${after}`);
  if (after !== newOwner) throw new Error("owner() did not change");
  if (network.name === "amoy") console.log(`https://amoy.polygonscan.com/tx/${tx.hash}`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
