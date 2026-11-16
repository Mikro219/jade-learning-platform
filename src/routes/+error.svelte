<script lang="ts">
	// The error page (plan A4): a fixed message and the request's id, nothing from the request.
	import { page } from '$app/state';
</script>

<svelte:head>
	<title>JADE</title>
</svelte:head>

<h1>{page.status}</h1>
<p>{page.error?.message}</p>
{#if page.error?.requestId}
	<p>Request id: <code>{page.error.requestId}</code></p>
{/if}
