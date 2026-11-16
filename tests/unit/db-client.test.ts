// The database tools' client (src/lib/server/db/roles.ts, B4, B6): TCP keepalive is on, with
// probes from 10 s of idleness on. Read from the pg connection the client hands its options to;
// nothing connects.
import { describe, expect, it } from 'vitest';
import { newClient } from '../../src/lib/server/db/index.ts';

describe('newClient', () => {
	it('turns TCP keepalive on with a 10 s initial delay', () => {
		const client = newClient('postgres://jade_owner:x@127.0.0.1:1/jade');
		const connection = (client as unknown as { connection: Record<string, unknown> }).connection;
		expect(connection['_keepAlive']).toBe(true);
		expect(connection['_keepAliveInitialDelayMillis']).toBe(10_000);
	});
});
