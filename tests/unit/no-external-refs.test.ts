// INV3 (static half): no absolute external URL in a src, href, @import or url() under src/ and
// static/, so no page can load anything from another origin (CLAUDE.md rule 5, ADR 0013).
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const root = fileURLToPath(new URL('../../', import.meta.url));
const SCANNED = ['src', 'static'];
const TEXT_EXT = /\.(svelte|html|ts|js|mjs|css|svg|json|webmanifest|txt|md)$/;

// An absolute URL: scheme-relative `//host` or any `scheme:` other than the inert data:, blob:,
// mailto:, tel: and the page-local `#`.
const ABS = String.raw`(?:\/\/|(?!(?:data|blob|mailto|tel):)[a-z][a-z0-9+.-]*:)`;
const PATTERNS: RegExp[] = [
	// src= href= srcset= poster= with a quoted value, optionally inside a Svelte {expression}
	new RegExp(
		String.raw`\b(?:src|srcset|href|xlink:href|poster)\s*=\s*\{?\s*["'\x60]\s*${ABS}`,
		'gi'
	),
	// @import "..." and @import url(...)
	new RegExp(String.raw`@import\s+(?:url\(\s*)?["']?\s*${ABS}`, 'gi'),
	// url(...) in CSS
	new RegExp(String.raw`\burl\(\s*["']?\s*${ABS}`, 'gi')
];

export function externalRefs(text: string): string[] {
	return PATTERNS.flatMap((p) => [...text.matchAll(p)].map((m) => m[0]));
}

function walk(dir: string): string[] {
	if (!existsSync(dir)) return [];
	return readdirSync(dir).flatMap((name) => {
		const path = join(dir, name);
		return statSync(path).isDirectory() ? walk(path) : TEXT_EXT.test(name) ? [path] : [];
	});
}

describe('external reference scanner', () => {
	it('finds external URLs in every form it checks', () => {
		const bad = [
			'<link href="https://fonts.googleapis.com/css?family=Inter">',
			"<script src='//cdn.example.com/x.js'></script>",
			'<img src={"https://example.com/a.png"}>',
			'<img srcset="http://example.com/a.png 2x">',
			'@import url("https://fonts.googleapis.com/css2");',
			"@import 'https://example.com/a.css';",
			'body { background: url(https://example.com/bg.png); }',
			'<use xlink:href="https://example.com/s.svg#i"/>'
		];
		for (const sample of bad) expect(externalRefs(sample).length, sample).toBeGreaterThan(0);
	});

	it('allows same-origin, relative and inert URLs', () => {
		const good = [
			'<link rel="icon" href="%sveltekit.assets%/favicon.svg">',
			'<a href="/about">',
			'<img src="./a.png">',
			'<a href="#main">',
			'<img src="data:image/png;base64,AAAA">',
			'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
			'background: url(/bg.png);'
		];
		for (const sample of good) expect(externalRefs(sample), sample).toEqual([]);
	});
});

describe('src/ and static/', () => {
	it('contain no absolute external URL in a src, href, @import or url()', () => {
		const problems: string[] = [];
		for (const dir of SCANNED) {
			for (const file of walk(join(root, dir))) {
				for (const ref of externalRefs(readFileSync(file, 'utf8'))) {
					problems.push(`${relative(root, file).split(sep).join('/')}: ${ref}`);
				}
			}
		}
		expect(problems).toEqual([]);
	});
});
