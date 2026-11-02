import path from "path";
import dotenv from "dotenv";
import { HardhatUserConfig } from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";

dotenv.config({ path: path.resolve(__dirname, "../.env") });

const issuerKey = process.env.ISSUER_PRIVATE_KEY?.trim();

const config: HardhatUserConfig = {
  solidity: "0.8.28",
  networks: {
    amoy: {
      url: process.env.AMOY_RPC_URL || "https://polygon-amoy-bor-rpc.publicnode.com",
      chainId: 80002,
      accounts: issuerKey ? [issuerKey] : [],
    },
  },
};

export default config;
