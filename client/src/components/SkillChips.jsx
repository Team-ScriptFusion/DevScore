const CATEGORY_LABELS = {
  language: 'Languages',
  framework: 'Frameworks',
  database: 'Databases',
  cloud_devops: 'Cloud & DevOps',
  mobile: 'Mobile',
  testing: 'Testing',
  design: 'Design',
  data_ml: 'Data & ML',
  web: 'Web',
  methodology: 'Methodology',
  vcs: 'Version Control',
};

const STATUS_COPY = {
  pending: 'Extracting skills…',
  failed: "Couldn't extract skills from this resume.",
  success_no_skills_found: 'No recognizable technical skills found in this resume.',
};

/**
 * Renders a resume's parsed skills (FR 28-32), grouped by category as
 * chips. Shared between the student's own view and the recruiter's
 * candidate views so both read the same shape consistently.
 */
export default function SkillChips({ status, byCategory, uncategorized, compact = false }) {
  if (status && status !== 'success') {
    return <p className="muted">{STATUS_COPY[status] || 'Skills not available yet.'}</p>;
  }

  const categories = Object.keys(byCategory || {});
  const hasUncategorized = Array.isArray(uncategorized) && uncategorized.length > 0;

  if (categories.length === 0 && !hasUncategorized) {
    return <p className="muted">No skills extracted yet.</p>;
  }

  return (
    <div className={`skill-groups ${compact ? 'skill-groups--compact' : ''}`}>
      {categories.map((category) => (
        <div className="skill-group" key={category}>
          {!compact && (
            <span className="skill-group__label">
              {CATEGORY_LABELS[category] || category}
            </span>
          )}
          <div className="skill-chips">
            {byCategory[category].map((skill) => (
              <span className="skill-chip" key={skill}>
                {skill}
              </span>
            ))}
          </div>
        </div>
      ))}
      {!compact && hasUncategorized && (
        <div className="skill-group">
          <span className="skill-group__label">Also mentioned</span>
          <div className="skill-chips">
            {uncategorized.map((term) => (
              <span className="skill-chip skill-chip--uncategorized" key={term}>
                {term}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
