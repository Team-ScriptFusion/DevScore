import { Link } from 'react-router-dom';

export default function NotFound() {
  return (
    <div className="centered-status">
      <div className="not-found">
        <p className="not-found__code">404</p>
        <h1 className="not-found__title">This page could not be found.</h1>
        <p className="muted">
          The link may be out of date, or the page may have moved.
        </p>
        <Link to="/" className="btn-primary not-found__cta">
          Back to DevScore
        </Link>
      </div>
    </div>
  );
}
