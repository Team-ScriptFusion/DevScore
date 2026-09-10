import { useLayoutEffect, useRef } from 'react';
import gsap from 'gsap';

/**
 * The conic-gradient score donut from the marketing hero (Home.jsx), extracted
 * so the dashboards can show a readiness score the same way the landing page
 * promises it. The fill is always brand teal rather than a red→green scale:
 * the band label beside it carries the semantic colour, so the meaning never
 * rests on hue alone (and a 41/100 doesn't render as an alarm).
 *
 * GSAP drives the number and the gradient stop from the same tween so they can
 * never disagree mid-animation. Under `prefers-reduced-motion` both are written
 * at their final value and no tween is created.
 */

const SIZES = {
  sm: { px: 40, stroke: 5, font: 0 },
  md: { px: 88, stroke: 8, font: 24 },
  lg: { px: 132, stroke: 11, font: 36 },
};

function ring(pct) {
  return `conic-gradient(var(--ds-primary) 0 ${pct}%, var(--ds-track) ${pct}% 100%)`;
}

export default function ScoreRing({
  value,
  size = 'md',
  showValue = true,
  suffix = null,
  label,
  animate = true,
}) {
  const { px, stroke, font } = SIZES[size] || SIZES.md;
  const ringRef = useRef(null);
  const valueRef = useRef(null);
  const target = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));

  useLayoutEffect(() => {
    const ringEl = ringRef.current;
    if (!ringEl) return undefined;

    const paint = (pct) => {
      ringEl.style.background = ring(pct);
      if (valueRef.current) valueRef.current.textContent = String(pct);
    };

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!animate || reduced) {
      paint(target);
      return undefined;
    }

    const counter = { value: 0 };
    const tween = gsap.to(counter, {
      value: target,
      duration: 1.0,
      ease: 'power1.out',
      onUpdate: () => paint(Math.round(counter.value)),
    });
    return () => tween.kill();
  }, [target, animate]);

  return (
    <div
      className={`score-ring score-ring--${size}`}
      style={{ '--ring-size': `${px}px`, '--ring-stroke': `${stroke}px` }}
      role="img"
      aria-label={label || `${target} out of 100`}
    >
      {/* the gradient track; the hole is punched by the inner element */}
      <div className="score-ring__track" ref={ringRef} style={{ background: ring(0) }} />
      <div className="score-ring__hole">
        {showValue && font > 0 && (
          <span className="score-ring__value" style={{ fontSize: `${font}px` }}>
            <span ref={valueRef}>0</span>
            {suffix && <span className="score-ring__suffix">{suffix}</span>}
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * The not-yet-scored counterpart — same footprint, so a card doesn't resize
 * when a score arrives. Rendered as a dashed track with no fill.
 */
export function ScoreRingEmpty({ size = 'md', hint = '—' }) {
  const { px, stroke } = SIZES[size] || SIZES.md;
  return (
    <div
      className={`score-ring score-ring--${size} score-ring--empty`}
      style={{ '--ring-size': `${px}px`, '--ring-stroke': `${stroke}px` }}
      role="img"
      aria-label="Not scored yet"
    >
      <div className="score-ring__track" />
      <div className="score-ring__hole">
        <span className="score-ring__placeholder">{hint}</span>
      </div>
    </div>
  );
}
