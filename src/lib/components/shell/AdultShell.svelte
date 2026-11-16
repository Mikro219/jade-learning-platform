<script lang="ts">
	// The adult shell (plan section 13, L2): compact, with a navigation region.
	import { resolve } from '$app/paths';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();
</script>

<div class="shell" data-shell="adult">
	<header class="bar">
		<a class="skip-link" href="#main">Skip to main content</a>
		<span class="brand">JADE</span>
		<nav aria-label="Main">
			<ul>
				<li><a href={resolve('/(student)')}>Home</a></li>
			</ul>
		</nav>
	</header>
	<main id="main" tabindex="-1">
		{@render children()}
	</main>
</div>

<style>
	.shell {
		position: relative;
		min-height: 100vh;
		background: var(--color-bg);
		font-size: var(--text-md);
	}

	.bar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-5);
		padding: var(--space-2) var(--space-4);
		background: var(--color-surface);
		border-bottom: 1px solid var(--color-border);
	}

	.brand {
		font-weight: 700;
	}

	nav ul {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-4);
		padding: 0;
		list-style: none;
	}

	nav a {
		display: inline-flex;
		align-items: center;
	}

	main {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-3);
		width: 100%;
		max-width: 60rem;
		margin-inline: auto;
		padding: var(--space-5) var(--space-4);
	}

	main :global(h1) {
		font-size: var(--text-2xl);
	}

	main :global(.button) {
		padding: var(--space-1) var(--space-4);
	}
</style>
