// Server hooks. `init` installs the process handlers (A4), then checks the configuration before
// the server listens (plan V3, V3a): on a ConfigError it reports the names through the logger and
// exits 1 itself, so the message cannot be swallowed by a generic handler. While building,
// nothing is checked, so the build needs no secret. `handle` gives every request an id and a
// request line (A2); `handleError` puts the id in every error body (A4).
import { building } from '$app/env';
import type { ServerInit } from '@sveltejs/kit/hooks';
import { ConfigError, getConfig, reportConfigError } from '#lib/server/config/index.ts';
import {
	closeDatabase,
	handleRequest,
	handleServerError,
	installProcessHandlers
} from '#lib/server/http/index.ts';
import { log } from '#lib/server/log/index.ts';

export const init: ServerInit = () => {
	if (building) return;
	installProcessHandlers();
	let config;
	try {
		config = getConfig();
	} catch (err) {
		if (err instanceof ConfigError) {
			reportConfigError(err);
			process.exit(1);
		}
		throw err;
	}
	log.setLevel(config.logLevel);
	process.once('sveltekit:shutdown', () => {
		void closeDatabase().finally(() => log.lifecycle('shutdown'));
	});
	log.lifecycle('boot');
};

export const handle = handleRequest;
export const handleError = handleServerError;
