// A host port for a test or tool to bind (plan PD11): bind 127.0.0.1 on port 0, read the
// port the kernel chose, close the socket. Run directly, it prints one such port.
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';

export function freePort(): Promise<number> {
	return new Promise((resolve, reject) => {
		const server = createServer();
		server.unref();
		server.on('error', reject);
		server.listen(0, '127.0.0.1', () => {
			const address = server.address();
			if (address === null || typeof address === 'string') {
				server.close();
				reject(new Error('free-port: no TCP address'));
				return;
			}
			const { port } = address;
			server.close((err) => (err ? reject(err) : resolve(port)));
		});
	});
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	process.stdout.write(`${await freePort()}\n`);
}
