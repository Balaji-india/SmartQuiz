// Shared helpers for deploy scripts: read keys from the root .env and rewrite a single KEY=value line in it.
import fs from "fs";
import path from "path";
import { ethers } from "hardhat";
import type { Wallet } from "ethers";

export const ENV_PATH = path.resolve(__dirname, "../../.env");

/** Address of a private key held in .env (the key itself is never printed). */
export function addressOfEnvKey(name: string): string {
  const key = process.env[name]?.trim();
  if (!key) throw new Error(`${name} is empty in .env`);
  return new ethers.Wallet(key.startsWith("0x") ? key : `0x${key}`).address;
}

/** Wallet for a private key held in .env, connected to the current network. */
export function walletOfEnvKey(name: string): Wallet {
  const key = process.env[name]?.trim();
  if (!key) throw new Error(`${name} is empty in .env`);
  return new ethers.Wallet(key.startsWith("0x") ? key : `0x${key}`, ethers.provider);
}

/** Replaces (or appends) the `name=` line in .env, keeping every other line and the line endings. */
export function writeEnvLine(name: string, value: string): void {
  const original = fs.readFileSync(ENV_PATH, "utf-8");
  const eol = original.includes("\r\n") ? "\r\n" : "\n";
  const lines = original.split(/\r?\n/);
  const pattern = new RegExp(`^${name}=`);
  let found = false;
  const updated = lines.map((line) => {
    if (pattern.test(line)) {
      found = true;
      return `${name}=${value}`;
    }
    return line;
  });
  if (!found) {
    // Keep a trailing newline at the end of the file.
    if (updated[updated.length - 1] === "") updated.splice(updated.length - 1, 0, `${name}=${value}`);
    else updated.push(`${name}=${value}`);
  }
  fs.writeFileSync(ENV_PATH, updated.join(eol), "utf-8");
}
