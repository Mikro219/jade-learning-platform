// A3 (B2): a failed readiness check reports `db: ok` only for an error the database server sent
// with a SQLSTATE outside the connection classes (08, 28, 3D, 53, 57). A Node errno code that
// happens to be five upper-case letters, or a refused connection, is `db: fail`.
import pg from 'pg';
import { describe, expect, it } from 'vitest';
import { readinessOfFailure } from '../../src/lib/server/http/index.ts';

function dbError(code: string): pg.DatabaseError {
	const err = new pg.DatabaseError('canary', 0, 'error');
	err.code = code;
	return err;
}

const errno = (code: string) => Object.assign(new Error('canary'), { code });

describe('readinessOfFailure', () => {
	it.each(['EPIPE', 'EBUSY', 'EPERM', 'EBADF', 'ECONNREFUSED', 'ETIMEDOUT'])(
		'a Node errno code (%s) is db: fail',
		(code) => {
			expect(readinessOfFailure(errno(code))).toEqual({ db: 'fail', migrations: 'unknown' });
		}
	);

	it('a SQLSTATE-shaped code on a plain Error is db: fail (not from the server)', () => {
		expect(readinessOfFailure(errno('42P01'))).toEqual({ db: 'fail', migrations: 'unknown' });
	});

	it.each(['08006', '08001', '28P01', '28000', '3D000', '53300', '57P01', '57P03', '57014'])(
		'a connection-class SQLSTATE (%s) is db: fail',
		(code) => {
			expect(readinessOfFailure(dbError(code))).toEqual({ db: 'fail', migrations: 'unknown' });
		}
	);

	it.each(['42P01', '42501', 'XX000'])(
		'a server error outside the connection classes (%s) is db: ok, migrations unknown',
		(code) => {
			expect(readinessOfFailure(dbError(code))).toEqual({ db: 'ok', migrations: 'unknown' });
		}
	);

	it('a DatabaseError without a well-formed code, and values that are not errors, are db: fail', () => {
		const noCode = new pg.DatabaseError('canary', 0, 'error');
		for (const value of [noCode, dbError('canary'), null, undefined, 'EPIPE', 42, {}]) {
			expect(readinessOfFailure(value)).toEqual({ db: 'fail', migrations: 'unknown' });
		}
	});

	it('a value whose prototype cannot be read is db: fail, not a throw', () => {
		const hostile = new Proxy(
			{},
			{
				getPrototypeOf() {
					throw new Error('canary');
				}
			}
		);
		expect(readinessOfFailure(hostile)).toEqual({ db: 'fail', migrations: 'unknown' });
	});
});
