// Ambient types for the app. SvelteKit reads the App namespace below.
declare global {
	namespace App {
		/** Every error body carries the request's id (plan A4), beside `status` and `message`. */
		interface Error {
			requestId: string;
		}
		interface Locals {
			/** Set by `handle` for every request (plan A2). */
			requestId: string;
		}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
