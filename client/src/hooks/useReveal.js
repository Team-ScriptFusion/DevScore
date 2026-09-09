import { useLayoutEffect, useRef } from 'react';
import gsap from 'gsap';

/**
 * Staggered entrance for a container's direct children, using the same motion
 * vocabulary as the marketing page's scroll reveals (power2.out, ~0.55s, small
 * upward travel) so a dashboard feels like the same product as the landing.
 *
 * Dashboards render above the fold and their content arrives asynchronously, so
 * this fires on mount rather than on scroll, and re-fires when `deps` change —
 * pass the loading flag so cards animate in once real data replaces skeletons,
 * not while the placeholder is still mounted.
 *
 * Returns a ref to attach to the container. Animation is skipped entirely under
 * `prefers-reduced-motion`; children are left at their natural state, never
 * stranded at opacity 0.
 */
export default function useReveal(deps = [], { enabled = true, stagger = 0.08 } = {}) {
  const ref = useRef(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !enabled) return undefined;

    const children = Array.from(el.children);
    if (children.length === 0) return undefined;

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined;

    const tween = gsap.fromTo(
      children,
      { opacity: 0, y: 18 },
      {
        opacity: 1,
        y: 0,
        duration: 0.55,
        ease: 'power2.out',
        stagger,
        clearProps: 'opacity,transform',
      },
    );
    return () => tween.kill();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, stagger, ...deps]);

  return ref;
}
