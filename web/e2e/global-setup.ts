import { execFileSync } from "node:child_process";
import path from "node:path";

import { E2E_NAME, E2E_PASSWORD, E2E_USERS } from "./support";

const repositoryRoot = path.resolve(__dirname, "..", "..");
const rateLimitPrefix = process.env.E2E_RATE_LIMIT_PREFIX ?? "estatehub:rl";

function compose(args: string[], input?: string): { status: number; output: string } {
  try {
    const output = execFileSync("docker", ["compose", ...args], {
      cwd: repositoryRoot,
      input,
      encoding: "utf8",
      stdio: ["pipe", "pipe", "pipe"],
    });
    return { status: 0, output };
  } catch (error) {
    const failure = error as { status?: number; stdout?: string; stderr?: string };
    return { status: failure.status ?? 1, output: `${failure.stdout ?? ""}${failure.stderr ?? ""}` };
  }
}

/**
 * Prepares the composed development stack: one administrator per scenario, created with
 * the real bootstrap CLI (idempotent), and fresh rate-limit counters so repeated runs
 * are not throttled. Never point this at a shared or production environment.
 */
export default function globalSetup(): void {
  if (process.env.E2E_SKIP_SETUP === "1") return;

  for (const email of Object.values(E2E_USERS)) {
    const result = compose(
      [
        "exec",
        "-T",
        "-e",
        "ESTATEHUB_DEBUG=false",
        "api",
        "python",
        "-m",
        "app.cli",
        "create-admin",
        "--email",
        email,
        "--name",
        E2E_NAME,
        "--password-stdin",
        "--allow-additional-admin",
      ],
      `${E2E_PASSWORD}\n`,
    );
    if (result.status !== 0 && !result.output.includes("email_already_exists")) {
      throw new Error(`Could not create the e2e account ${email}:\n${result.output}`);
    }
  }

  const cleared = compose([
    "exec",
    "-T",
    "redis",
    "sh",
    "-c",
    `redis-cli --scan --pattern '${rateLimitPrefix}:*' | xargs -r redis-cli del`,
  ]);
  if (cleared.status !== 0) {
    throw new Error(`Could not reset rate limits:\n${cleared.output}`);
  }
}
