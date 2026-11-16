<script lang="ts">
	// The error page (plan A4): a fixed message and the request's id, nothing from the request.
	// It renders inside the root layout only, so it brings its own shell: the student shell, the
	// one every unknown URL and, outside development and test, every /dev/ page lands on.
	import { page } from '$app/state';
	import StudentShell from '#lib/components/shell/StudentShell.svelte';
</script>

<svelte:head>
	<title>JADE</title>
</svelte:head>

<StudentShell>
	<h1>{page.status}</h1>
	<p>{page.error?.message}</p>
	{#if page.error?.requestId}
		<p>Request id: <code>{page.error.requestId}</code></p>
	{/if}
</StudentShell>
