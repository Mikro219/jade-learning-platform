<script lang="ts">
	// The student route group: every page is wrapped in the student shell (plan section 13, L2).
	import StudentShell from '#lib/components/shell/StudentShell.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

<StudentShell>
	{@render children()}
</StudentShell>
