// A module under src/lib/server/ is reached only through its index.ts (ARCHITECTURE.md section 4,
// plan PD10). config, db and log import nothing from SvelteKit, so tools can use them.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const root = fileURLToPath(new URL('../../', import.meta.url));
const serverDir = join(root, 'src/lib/server');
const MODULES = ['auth', 'codes', 'content', 'events', 'analytics'] as const;
const FRAMEWORK_FREE = ['config', 'db', 'log'] as const;
const SCANNED_DIRS = ['src', 'tests', 'tools'];
const SOURCE_EXT = /\.(ts|js|mjs|cjs|svelte)$/;

function walk(dir: string): string[] {
	if (!existsSync(dir)) return [];
	return readdirSync(dir).flatMap((name) => {
		const path = join(dir, name);
		if (name === 'node_modules') return [];
		return statSync(path).isDirectory() ? walk(path) : SOURCE_EXT.test(name) ? [path] : [];
	});
}

/** Every module specifier in a source file: static, dynamic and re-export forms. */
export function specifiers(source: string): string[] {
	const out: string[] = [];
	const patterns = [
		/\bimport\s+(?:type\s+)?[^'"`;]*?\bfrom\s*['"]([^'"]+)['"]/g,
		/\bimport\s*['"]([^'"]+)['"]/g,
		/\bexport\s+(?:type\s+)?[^'"`;]*?\bfrom\s*['"]([^'"]+)['"]/g,
		/\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g
	];
	for (const pattern of patterns) for (const m of source.matchAll(pattern)) out.push(m[1]!);
	return out;
}

/** The repo-relative path a specifier points at, or null for a package import. */
export function target(fromFile: string, spec: string): string | null {
	let abs: string;
	if (spec.startsWith('#lib/')) abs = join(root, 'src/lib', spec.slice('#lib/'.length));
	else if (spec === '#lib') abs = join(root, 'src/lib');
	else if (spec.startsWith('$lib/')) abs = join(root, 'src/lib', spec.slice('$lib/'.length));
	else if (spec.startsWith('.')) abs = resolve(dirname(fromFile), spec);
	else return null;
	return relative(root, abs).split(sep).join('/');
}

/** Why an import breaks a module boundary, or null when it does not. */
export function violation(fromRel: string, targetRel: string): string | null {
	const m = /^src\/lib\/server\/([^/]+)(?:\/(.*))?$/.exec(targetRel);
	if (!m) return null;
	const [, mod, rest] = m;
	if (fromRel.startsWith(`src/lib/server/${mod}/`)) return null;
	if (rest === undefined || /^index(\.(ts|js))?$/.test(rest)) return null;
	return `${fromRel} imports ${targetRel}, inside module ${mod}; import its index.ts instead`;
}

describe('module folders', () => {
	it.each(MODULES)('src/lib/server/%s/index.ts exists', (mod) => {
		expect(existsSync(join(serverDir, mod, 'index.ts'))).toBe(true);
	});
});

describe('module boundaries', () => {
	it('the rule recognises deep imports and allows index imports', () => {
		expect(violation('src/routes/+page.ts', 'src/lib/server/codes/hmac.ts')).not.toBeNull();
		expect(violation('tests/unit/x.test.ts', 'src/lib/server/db/pool')).not.toBeNull();
		expect(violation('src/routes/+page.ts', 'src/lib/server/codes/index.ts')).toBeNull();
		expect(violation('src/routes/+page.ts', 'src/lib/server/codes')).toBeNull();
		expect(violation('src/lib/server/codes/a.ts', 'src/lib/server/codes/b.ts')).toBeNull();
		expect(target(join(root, 'src/routes/x.ts'), '#lib/server/auth/session.ts')).toBe(
			'src/lib/server/auth/session.ts'
		);
		expect(target(join(root, 'src/routes/x.ts'), '../lib/server/auth/session')).toBe(
			'src/lib/server/auth/session'
		);
		expect(target(join(root, 'src/routes/x.ts'), '@sveltejs/kit')).toBeNull();
		expect(
			specifiers(`import a from './a';\nexport { b } from "./b";\nawait import('./c');`)
		).toEqual(['./a', './b', './c']);
	});

	it('no file outside a module imports a path inside it other than index.ts', () => {
		const problems: string[] = [];
		for (const dir of SCANNED_DIRS) {
			for (const file of walk(join(root, dir))) {
				const fromRel = relative(root, file).split(sep).join('/');
				for (const spec of specifiers(readFileSync(file, 'utf8'))) {
					const t = target(file, spec);
					const problem = t === null ? null : violation(fromRel, t);
					if (problem) problems.push(problem);
				}
			}
		}
		expect(problems).toEqual([]);
	});

	it('config, db and log import nothing from SvelteKit', () => {
		const problems: string[] = [];
		for (const mod of FRAMEWORK_FREE) {
			for (const file of walk(join(serverDir, mod))) {
				for (const spec of specifiers(readFileSync(file, 'utf8'))) {
					if (spec.startsWith('$app/') || spec.startsWith('@sveltejs/kit')) {
						problems.push(`${relative(root, file)} imports ${spec}`);
					}
				}
			}
		}
		expect(problems).toEqual([]);
	});
});
