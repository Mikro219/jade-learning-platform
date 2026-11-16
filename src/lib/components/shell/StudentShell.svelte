<script lang="ts">
	// The student shell (plan section 13, L2): body text 18px or larger, one column, minimal
	// chrome. Targets are at least --tap-min on each side (base.css, keyed on data-shell).
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();
</script>

<div class="shell" data-shell="student">
	<header class="bar">
		<a class="skip-link" href="#main">Skip to main content</a>
		<span class="brand">JADE</span>
	</header>
	<main id="main" tabindex="-1">
		{@render children()}
	</main>
</div>

<style>
	.shell {
		position: relative;
		display: flex;
		flex-direction: column;
		min-height: 100vh;
		font-size: var(--text-lg);
	}

	.bar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-4);
		padding: var(--space-2) var(--space-4);
		border-bottom: 1px solid var(--color-border);
	}

	.brand {
		font-size: var(--text-xl);
		font-weight: 700;
	}

	main {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-5);
		width: 100%;
		max-width: var(--measure);
		margin-inline: auto;
		padding: var(--space-6) var(--space-4);
	}

	main :global(h1) {
		font-size: var(--text-3xl);
	}
</style>
