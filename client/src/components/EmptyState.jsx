import { InboxIcon } from './DashboardIcons.jsx';

/**
 * Empty states used to be a bare `<p class="muted">`, which read as a bug
 * rather than a state. This gives every "nothing here yet" branch the same
 * shape: an icon tile in the brand-soft treatment, a heading that names the
 * state, one line of explanation, and — where there's something useful to do —
 * an action. `action` is a ready-made element (a Link or a button) so the
 * caller keeps control of navigation vs. handler.
 */
export default function EmptyState({
  Icon = InboxIcon,
  title,
  description,
  action,
  compact = false,
}) {
  return (
    <div className={`empty-state${compact ? ' empty-state--compact' : ''}`}>
      <span className="empty-state__icon">
        <Icon />
      </span>
      <p className="empty-state__title">{title}</p>
      {description && <p className="empty-state__body">{description}</p>}
      {action && <div className="empty-state__action">{action}</div>}
    </div>
  );
}
