// .env.example documents every variable (plan V4, INV4): the config schemas' keys, every
// process.env.NAME read in tools/, every ${NAME} in the Compose files; every secret is empty.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseEnv } from 'node:util';
import { describe, expect, it } from 'vitest';
import { CONFIG_KEYS, SECRET_KEYS } from '../../src/lib/server/config/index.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));
const text = readFileSync(join(root, '.env.example'), 'utf8');
const example = parseEnv(text);
const keys = new Set(Object.keys(example));

function walk(dir: string): string[] {
	if (!existsSync(dir)) return [];
	return readdirSync(dir).flatMap((name) => {
		const path = join(dir, name);
		return statSync(path).isDirectory() ? walk(path) : /\.(ts|js|mjs|sh)$/.test(name) ? [path] : [];
	});
}

/** Names read as `process.env.NAME` or `process.env['NAME']`. */
export function envReads(source: string): string[] {
	const names = new Set<string>();
	for (const m of source.matchAll(/process\.env\.([A-Za-z_][A-Za-z0-9_]*)/g)) names.add(m[1]!);
	for (const m of source.matchAll(/process\.env\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]/g)) {
		names.add(m[1]!);
	}
	for (const m of source.matchAll(/\benv\[\s*['"]([A-Z_][A-Z0-9_]*)['"]\s*\]/g)) names.add(m[1]!);
	return [...names];
}

/** Names interpolated as `${NAME}`, `${NAME:?}`, `${NAME:-x}` and the like. */
export function composeVars(source: string): string[] {
	return [...source.matchAll(/\$\{([A-Za-z_][A-Za-z0-9_]*)/g)].map((m) => m[1]!);
}

const isSecret = (key: string) =>
	(SECRET_KEYS as readonly string[]).includes(key) || /PASSWORD|SECRET|PEPPER|TOKEN/.test(key);

describe('.env.example', () => {
	it('the scanners find what they look for', () => {
		expect(envReads("process.env.A_B; process.env['C']; env['D_E']")).toEqual(['A_B', 'C', 'D_E']);
		expect(composeVars('x: ${A:?}\ny: ${B:-1}\nz: $${NOT}')).toContain('A');
	});

	it('has every key of the config schemas', () => {
		expect(CONFIG_KEYS.filter((k) => !keys.has(k))).toEqual([]);
	});

	it('has every variable read in tools/', () => {
		const missing = walk(join(root, 'tools'))
			.flatMap((file) => envReads(readFileSync(file, 'utf8')))
			.filter((name) => !keys.has(name));
		expect(missing).toEqual([]);
	});

	it('has every variable the Compose files interpolate', () => {
		const files = readdirSync(root).filter((name) => /^compose.*\.ya?ml$/.test(name));
		const missing = files
			.flatMap((file) => composeVars(readFileSync(join(root, file), 'utf8')))
			.filter((name) => !keys.has(name));
		expect(missing).toEqual([]);
	});

	it('leaves every secret empty', () => {
		const secrets = [...keys].filter(isSecret);
		expect(secrets).toEqual(expect.arrayContaining([...SECRET_KEYS]));
		for (const key of secrets) expect({ key, value: example[key] }).toEqual({ key, value: '' });
	});

	it('documents every variable with a comment line above it', () => {
		const lines = text.split('\n');
		for (const key of keys) {
			const at = lines.findIndex((line) => line.startsWith(`${key}=`));
			expect({ key, comment: lines[at - 1]?.startsWith('#') }).toEqual({ key, comment: true });
		}
	});
});
