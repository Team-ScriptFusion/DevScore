/**
 * DevScore brand lockup — the full "D + check + DevScore" logo.
 *
 * `theme="dark"` uses the white-wordmark artwork for dark surfaces (the app
 * sidebar); the default `theme="light"` uses the black-wordmark artwork for
 * light surfaces (the auth panels). `subtitle` renders the small contextual
 * tagline beneath the lockup — it is not part of the brand mark itself.
 */
export default function Logo({ height = 28, theme = 'light', subtitle }) {
  const src =
    theme === 'dark' ? '/brand/devscore-logo.png' : '/brand/devscore-logo-black.png';

  return (
    <span className="sidebar__brand" style={{ padding: 0 }}>
      <span className="sidebar__brand-text">
        <img
          src={src}
          alt="DevScore"
          style={{ height, width: 'auto', display: 'block', alignSelf: 'flex-start' }}
        />
        {subtitle && <span className="sidebar__brand-sub">{subtitle}</span>}
      </span>
    </span>
  );
}
