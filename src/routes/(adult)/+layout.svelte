<script lang="ts">
	// The adult route group: every page is wrapped in the adult shell (plan section 13, L2).
	import AdultShell from '#lib/components/shell/AdultShell.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

<AdultShell>
	{@render children()}
</AdultShell>
