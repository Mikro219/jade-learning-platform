<script lang="ts">
	// The staff shell (plan section 13, L2): dense, with a distinct colour band and a "Staff"
	// label, so a staff screen is never mistaken for a student or adult one.
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();
</script>

<div class="shell" data-shell="staff">
	<header class="band">
		<a class="skip-link" href="#main">Skip to main content</a>
		<span class="label">Staff</span>
		<span class="brand">JADE</span>
	</header>
	<main id="main" tabindex="-1">
		{@render children()}
	</main>
</div>

<style>
	.shell {
		position: relative;
		min-height: 100vh;
		font-size: var(--text-sm);
		line-height: 1.4;
	}

	.band {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1) var(--space-3);
		padding: var(--space-2) var(--space-4);
		background: var(--color-staff-band);
		color: var(--color-on-staff-band);
	}

	.band :global(a) {
		color: var(--color-on-staff-band);
	}

	.band :global(:focus-visible) {
		outline-color: var(--color-focus-on-dark);
	}

	.label {
		padding: 0 var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-on-staff-band);
		color: var(--color-staff-band);
		font-size: var(--text-xs);
		font-weight: 700;
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.brand {
		font-weight: 700;
	}

	main {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-2);
		width: 100%;
		padding: var(--space-3) var(--space-4);
	}

	main :global(h1) {
		font-size: var(--text-xl);
	}

	main :global(.button) {
		padding: var(--space-1) var(--space-3);
	}
</style>
