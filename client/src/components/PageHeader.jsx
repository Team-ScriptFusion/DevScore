/**
 * The title block every dashboard screen opens with. Replaces the bare
 * `<h1 class="page-title">` + `<p class="page-subtitle">` pair that was
 * repeated across all nine pages, and gives them a consistent slot for
 * right-aligned actions so page-level CTAs stop living inside table headers.
 */
export default function PageHeader({ eyebrow, title, subtitle, actions }) {
  return (
    <header className="page-header">
      <div className="page-header__text">
        {eyebrow && <span className="page-header__eyebrow">{eyebrow}</span>}
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  );
}
