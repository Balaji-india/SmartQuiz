// Amoy fee floor shared by every script that sends a transaction (and mirrored in api/app/chain/service.py).
// Amoy rejects or strands priority fees under 25 gwei and Hardhat's defaults can be lower, so the tip is
// max(network tip, 30 gwei) and the max fee is 2 x base fee + tip.
import { ethers } from "hardhat";
import type { Provider } from "ethers";

export const MIN_TIP_GWEI = 30n;

export type Fees = { maxPriorityFeePerGas: bigint; maxFeePerGas: bigint };

type RpcProvider = Provider & { send(method: string, params: unknown[]): Promise<unknown> };

export async function amoyFees(provider: RpcProvider): Promise<Fees> {
  const latest = await provider.getBlock("latest");
  const base = latest?.baseFeePerGas ?? 0n;
  let netTip = 0n;
  try {
    netTip = BigInt((await provider.send("eth_maxPriorityFeePerGas", [])) as string);
  } catch {
    // Some RPCs do not support it; the floor applies.
  }
  const floor = ethers.parseUnits(MIN_TIP_GWEI.toString(), "gwei");
  const tip = netTip > floor ? netTip : floor;
  return { maxPriorityFeePerGas: tip, maxFeePerGas: base * 2n + tip };
}

/** Replacing a pending tx at the same nonce needs both fees at least ~10% higher; use 12.5%. */
export function bumped(fees: Fees, pending: Fees): Fees {
  const up = (x: bigint) => (x * 9n) / 8n + 1n;
  const max = (a: bigint, b: bigint) => (a > b ? a : b);
  const tip = max(fees.maxPriorityFeePerGas, up(pending.maxPriorityFeePerGas));
  return { maxPriorityFeePerGas: tip, maxFeePerGas: max(max(fees.maxFeePerGas, up(pending.maxFeePerGas)), tip) };
}

export function formatFees(f: Fees): string {
  return `tip ${ethers.formatUnits(f.maxPriorityFeePerGas, "gwei")} gwei, max fee ${ethers.formatUnits(f.maxFeePerGas, "gwei")} gwei`;
}
