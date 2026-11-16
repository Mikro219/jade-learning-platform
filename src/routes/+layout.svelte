<script lang="ts">
	// The root layout: the design tokens and base styles (plan section 13, L1). Each route group's
	// layout wraps its pages in that group's shell (L2).
	import '#lib/styles/tokens.css';
	import '#lib/styles/base.css';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

{@render children()}
