<!-- Dev-only (plan PD8, L3): neutral sample elements in the staff shell. No form field (rule 1), no
teaching content (rule 7). -->
<script lang="ts">
	import { resolve } from '$app/paths';
</script>

<svelte:head>
	<title>Staff shell - JADE</title>
</svelte:head>

<h1>Staff shell</h1>
<p>A sample paragraph, to show the staff shell's text size, spacing and colours.</p>
<a href={resolve('/(student)')}>A sample link</a>
<button type="button" class="button">A sample button</button>
