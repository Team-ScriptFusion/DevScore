/**
 * Metric tile used across the Admin and Recruiter dashboards.
 *
 * `sublabel` carries the context a bare number can't — "across 12 scored
 * candidates" under an average, for instance. It is deliberately not a trend:
 * there is no historical data to compare against, and a fabricated "+12% vs
 * last month" would be a lie the layout tempts you into.
 */
export default function StatCard({ label, value, Icon, sublabel, suffix }) {
  return (
    <div className="stat-card card">
      <div className="stat-card__body">
        <p className="stat-card__label">{label}</p>
        <p className="stat-card__value">
          {value}
          {suffix && <span className="stat-card__suffix">{suffix}</span>}
        </p>
        {sublabel && <p className="stat-card__sublabel">{sublabel}</p>}
      </div>
      {Icon && (
        <span className="stat-card__icon">
          <Icon />
        </span>
      )}
    </div>
  );
}
