/**
 * DevScore brand mark — the teal "D + check" logo glyph plus the wordmark,
 * matching the marketing site. The artwork lives in /public/brand and reads
 * cleanly on both the light auth panels and the dark sidebar.
 */
export default function Logo({ size = 28, showText = true, subtitle }) {
  return (
    <span className="sidebar__brand" style={{ padding: 0 }}>
      <img
        src="/brand/devscore-mark.png"
        width={size}
        height={size}
        alt=""
        aria-hidden="true"
        style={{ display: 'block', flexShrink: 0 }}
      />
      {showText && (
        <span className="sidebar__brand-text">
          <span className="sidebar__brand-name">DevScore</span>
          {subtitle && <span className="sidebar__brand-sub">{subtitle}</span>}
        </span>
      )}
    </span>
  );
}
