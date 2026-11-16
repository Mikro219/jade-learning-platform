// Reads `.env` into `process.env` outside production (plan V6). `vite.config.ts`,
// `playwright.config.ts` and the tools call it; `node build` never reads a file. A variable that
// is already set keeps its value (process.loadEnvFile does not overwrite).
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const DEFAULT_PATH = fileURLToPath(new URL('../.env', import.meta.url));

/** Load the env file at `path` (default: the checkout's `.env`). Returns whether it was read. */
export function loadEnv(path: string = DEFAULT_PATH): boolean {
	// Read through a variable, not as the literal `process.env.NODE_ENV`, which a bundler (Vite
	// bundles its config file) may replace.
	const env = process.env;
	if (env['NODE_ENV'] === 'production') return false;
	if (!existsSync(path)) return false;
	process.loadEnvFile(path);
	return true;
}
