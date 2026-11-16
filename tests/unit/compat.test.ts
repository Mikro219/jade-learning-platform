// tools/ci/compat.ts's verdicts (plan X4, 12.1): the ledger comparison of steps 1 and 3, and the
// exit codes of steps 2 and 3 that `pnpm ci:compat --self-test` reads, so that only a
// compatibility failure counts as the breaking fixture being caught.
import { describe, expect, it } from 'vitest';
import {
	COMPAT_EXIT,
	classifyReadyz,
	classifyStep3,
	ledgerMatches
} from '../../tools/ci/compat.ts';

const a = { name: '0000_baseline', sha256: 'a'.repeat(64) };
const b = { name: '0001_next', sha256: 'b'.repeat(64) };

describe('ledgerMatches', () => {
	it('is true only for the same names and hashes in the same order', () => {
		expect(ledgerMatches([a, b], [a, b])).toBe(true);
		expect(ledgerMatches([], [])).toBe(true);
		expect(ledgerMatches([a], [a, b])).toBe(false);
		expect(ledgerMatches([a, b], [a])).toBe(false);
		expect(ledgerMatches([b, a], [a, b])).toBe(false);
		expect(ledgerMatches([a, { ...b, sha256: 'c'.repeat(64) }], [a, b])).toBe(false);
		expect(ledgerMatches([a, { ...b, name: '0001_other' }], [a, b])).toBe(false);
	});
});

describe('classifyReadyz (step 2)', () => {
	const body = (migrations: string, db = 'ok') =>
		JSON.stringify({ status: 'not_ready', checks: { db, migrations }, requestId: 'x' });

	it('200 passes', () => {
		expect(classifyReadyz(200, '{"status":"ready"}').code).toBe(COMPAT_EXIT.ok);
	});

	it('503 with migrations not ok is the schema breaking the base app (code 12)', () => {
		for (const m of ['unknown', 'behind', 'mismatch']) {
			const v = classifyReadyz(503, body(m));
			expect(v.code, m).toBe(COMPAT_EXIT.step2);
			expect(v.detail).toContain(`db: ok, migrations: ${m}`);
		}
	});

	it('anything else is a step-2 failure that is not a compatibility verdict (code 16)', () => {
		// What readiness answers when the base cannot reach its database or hits the 2 s limit.
		expect(classifyReadyz(503, body('unknown', 'fail')).code).toBe(COMPAT_EXIT.step2Other);
		expect(classifyReadyz(503, JSON.stringify({ checks: { migrations: 'unknown' } })).code).toBe(
			COMPAT_EXIT.step2Other
		);
		expect(classifyReadyz(503, 'not json').code).toBe(COMPAT_EXIT.step2Other);
		expect(classifyReadyz(500, body('unknown')).code).toBe(COMPAT_EXIT.step2Other);
		expect(classifyReadyz(0, '').code).toBe(COMPAT_EXIT.step2Other);
	});

	it('the codes the self-test accepts are exactly step 2 and step 3', () => {
		expect(COMPAT_EXIT.step2).toBe(12);
		expect(COMPAT_EXIT.step3).toBe(13);
		const others = Object.entries(COMPAT_EXIT)
			.filter(([k]) => k !== 'step2' && k !== 'step3')
			.map(([, v]) => v);
		expect(others).not.toContain(12);
		expect(others).not.toContain(13);
		expect(new Set(Object.values(COMPAT_EXIT)).size).toBe(Object.keys(COMPAT_EXIT).length);
	});
});

describe('classifyStep3 (step 3)', () => {
	const report = (statuses: string[], failedTests: number) => ({
		numTotalTestSuites: statuses.length,
		numFailedTests: failedTests,
		testResults: statuses.map((status) => ({ status }))
	});

	it('every file passed and Vitest exited 0: ok', () => {
		expect(classifyStep3(report(['passed', 'passed'], 0), 0).code).toBe(COMPAT_EXIT.ok);
	});

	it('the harness started and files failed: a compatibility failure (code 13)', () => {
		const v = classifyStep3(report(['passed', 'failed'], 2), 1);
		expect(v.code).toBe(COMPAT_EXIT.step3);
		expect(v.detail).toContain('2 test(s) in 1 of 2 file(s)');
	});

	it('no report, or a report with no file (global setup failed): a harness failure (17)', () => {
		expect(classifyStep3(null, 1).code).toBe(COMPAT_EXIT.step3Harness);
		expect(classifyStep3(report([], 0), 1).code).toBe(COMPAT_EXIT.step3Harness);
	});

	it('all tests passed but Vitest failed (setup or teardown): a harness failure (17)', () => {
		expect(classifyStep3(report(['passed'], 0), 1).code).toBe(COMPAT_EXIT.step3Harness);
	});
});
