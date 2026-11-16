<script lang="ts">
	// The staff route group: every page is wrapped in the staff shell (plan section 13, L2).
	import StaffShell from '#lib/components/shell/StaffShell.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

<StaffShell>
	{@render children()}
</StaffShell>
