// Caddy's logs (plan D4, INV2, CLAUDE.md rule 4): no access log, and no line Caddy writes carries
// a client address, a URI, a query string or a request header. Checked after normal requests,
// after requests while the app container is stopped (502, which Caddy logs as an error with the
// request attached unless the filter deletes it), and after broken TLS handshakes (which the
// standard-library HTTP logger reports with the peer's address unless it is excluded).
import { connect as tcpConnect } from 'node:net';
import { connect as tlsConnect } from 'node:tls';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import {
	docker,
	httpGet,
	httpsGet,
	inspect,
	projectContainers,
	startStack,
	stopStack,
	waitFor,
	type Stack
} from '../support/infra.ts';

const CODE = 'CANARYCODE7Q4X';
const COOKIE = 'CanaryCookie9z8y';
const QUERY = 'canaryquery5k2m';
const HEADER = 'CanaryHeader3j1h';

let stack: Stack;
let ca: string;
let logs = '';
let appLogs = '';

/** Send bytes that are not a TLS ClientHello, then close. */
function garbageHandshake(port: number): Promise<void> {
	return new Promise((resolve) => {
		const socket = tcpConnect({ host: '127.0.0.1', port }, () => {
			socket.write('GET / HTTP/1.1\r\nHost: localhost\r\n\r\n');
		});
		socket.setTimeout(3000, () => socket.destroy());
		socket.on('data', () => socket.destroy());
		socket.once('close', () => resolve());
		socket.once('error', () => resolve());
	});
}

/** A TLS handshake for a name Caddy has no certificate for, and one that is cut off. */
function badSniHandshake(port: number): Promise<void> {
	return new Promise((resolve) => {
		const socket = tlsConnect({
			host: '127.0.0.1',
			port,
			servername: 'nosuch.invalid',
			rejectUnauthorized: false
		});
		socket.setTimeout(3000, () => socket.destroy());
		socket.once('secureConnect', () => socket.destroy());
		socket.once('close', () => resolve());
		socket.once('error', () => resolve());
	});
}

function cutHandshake(port: number): Promise<void> {
	return new Promise((resolve) => {
		const socket = tcpConnect({ host: '127.0.0.1', port }, () => {
			// The first bytes of a TLS record header (handshake, TLS 1.0), then nothing.
			socket.end(Buffer.from([0x16, 0x03, 0x01, 0x00, 0xff, 0x01]));
		});
		socket.setTimeout(3000, () => socket.destroy());
		socket.once('close', () => resolve());
		socket.once('error', () => resolve());
	});
}

const requests = async () => {
	const headers = { cookie: `jade_session=${COOKIE}`, 'x-canary': HEADER, 'user-agent': HEADER };
	await httpsGet(stack.httpsPort, `/redeem?code=${CODE}&q=${QUERY}`, { ca, headers }).catch(
		() => {}
	);
	await httpsGet(stack.httpsPort, `/healthz?q=${QUERY}`, { ca, headers }).catch(() => {});
	await httpsGet(stack.httpsPort, `/media/${QUERY}.mp4`, { ca, headers }).catch(() => {});
	await httpGet(stack.httpPort, `/redeem?code=${CODE}`, headers).catch(() => {});
};

/** Every IPv4 gateway of the project's networks and every address of its containers. */
async function stackAddresses(): Promise<{ gateways: string[]; containers: string[] }> {
	const gateways = new Set<string>();
	for (const net of ['edge', 'backend']) {
		const r = await docker([
			'network',
			'inspect',
			'--format',
			'{{range .IPAM.Config}}{{.Gateway}} {{end}}',
			`${stack.project}_${net}`
		]);
		for (const g of r.stdout.split(/\s+/).filter(Boolean)) gateways.add(g);
	}
	const containers = new Set<string>();
	for (const id of await projectContainers(stack.project)) {
		const nets = await inspect<Record<string, { IPAddress?: string }> | null>(
			id,
			'.NetworkSettings.Networks'
		);
		for (const n of Object.values(nets ?? {})) if (n.IPAddress) containers.add(n.IPAddress);
	}
	return { gateways: [...gateways], containers: [...containers] };
}

let addresses: { gateways: string[]; containers: string[] };

beforeAll(async () => {
	stack = await startStack('caddylogs');
	ca = await stack.ca();
	addresses = await stackAddresses();

	// Normal requests.
	await requests();
	// With the app stopped: 502s, which Caddy logs as errors.
	expect((await stack.compose(['stop', 'app'])).code).toBe(0);
	await requests();
	const r502 = await httpsGet(stack.httpsPort, `/redeem?code=${CODE}`, { ca }).catch(() => null);
	// Broken TLS handshakes.
	await garbageHandshake(stack.httpsPort);
	await cutHandshake(stack.httpsPort);
	await badSniHandshake(stack.httpsPort);
	// Wait until the 502 has been logged, so the log under test holds the error path.
	await waitFor(async () => {
		const r = await stack.compose(['logs', '--no-color', '--no-log-prefix', 'caddy']);
		return /"status":502/.test(r.stdout + r.stderr);
	}, 20_000);
	const r = await stack.compose(['logs', '--no-color', '--no-log-prefix', 'caddy']);
	logs = r.stdout + r.stderr;
	// The app's own log, from the requests it served before it was stopped (INV1 seen from the
	// stack: Caddy forwards no client address, and the app logs no code or cookie).
	const app = await stack.compose(['logs', '--no-color', '--no-log-prefix', 'app']);
	appLogs = app.stdout + app.stderr;
	expect(r502?.status).toBe(502);
});
afterAll(async () => {
	await stopStack('caddylogs', stack);
});

const lines = () => logs.split('\n').filter((l) => l.trim() !== '');

describe("Caddy's log", () => {
	it('holds the 502 error line, so the error path was exercised', () => {
		expect(lines().some((l) => l.includes('"status":502'))).toBe(true);
	});

	it('has no access log entry', () => {
		expect(lines().filter((l) => /"logger":"http\.log\.access/.test(l))).toEqual([]);
	});

	it('has no request object, remote_ip or client_ip key', () => {
		for (const line of lines()) {
			expect(line).not.toMatch(/"(request|remote_ip|client_ip|remote_addr|headers|uri)"\s*:/);
		}
	});

	it('carries none of the canaries: code, cookie, query, header', () => {
		for (const canary of [CODE, COOKIE, QUERY, HEADER]) expect(logs).not.toContain(canary);
	});

	it('carries no Docker gateway address the requests came from', () => {
		expect(addresses.gateways.length).toBeGreaterThan(0);
		for (const gateway of addresses.gateways) {
			expect(logs).not.toMatch(
				new RegExp(`(^|[^0-9.])${gateway.replaceAll('.', '\\.')}([^0-9]|$)`)
			);
		}
	});

	it('every IPv4 address in it is a stack container or Docker DNS, never a client', () => {
		const allowed = new Set([...addresses.containers, '127.0.0.11', '0.0.0.0']);
		const unexpected = new Set<string>();
		for (const line of lines()) {
			// The admin endpoint's start-up line lists its own loopback origins (localhost:2019).
			const own = /"logger":"admin"/.test(line) ? new Set(['127.0.0.1']) : new Set<string>();
			for (const m of line.matchAll(/(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])/g)) {
				if (!allowed.has(m[1]!) && !own.has(m[1]!)) unexpected.add(m[1]!);
			}
		}
		expect([...unexpected]).toEqual([]);
	});

	it("the app's log carries no canary and no Docker gateway address", () => {
		// It did log the requests it served, so the absence below means something.
		expect(appLogs).toMatch(/"msg":"request"/);
		for (const canary of [CODE, COOKIE, QUERY, HEADER]) expect(appLogs).not.toContain(canary);
		for (const gateway of addresses.gateways) {
			expect(appLogs).not.toMatch(
				new RegExp(`(^|[^0-9.])${gateway.replaceAll('.', '\\.')}([^0-9]|$)`)
			);
		}
	});

	it('no line from the standard-library HTTP logger (TLS handshake errors)', () => {
		expect(lines().filter((l) => /http\.stdlib|TLS handshake error/.test(l))).toEqual([]);
	});
});
