// Server hooks. `init` checks the configuration before the server listens (plan V3, V3a): on a
// ConfigError it reports the names and exits 1 itself, so the message cannot be swallowed by a
// generic handler. While building, nothing is checked, so the build needs no secret.
import { building } from '$app/env';
import type { ServerInit } from '@sveltejs/kit/hooks';
import { ConfigError, getConfig, reportConfigError } from '#lib/server/config/index.ts';

export const init: ServerInit = () => {
	if (building) return;
	try {
		getConfig();
	} catch (err) {
		if (err instanceof ConfigError) {
			reportConfigError(err);
			process.exit(1);
		}
		throw err;
	}
};
