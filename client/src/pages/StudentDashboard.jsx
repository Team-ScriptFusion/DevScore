import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { githubApi, resumeApi } from '../lib/api.js';
import { ResumeIcon, GithubMiningIcon } from '../components/FeatureIcons.jsx';

function SetupCard({ Icon, done, title, description, doneLabel, actionLabel, to, meta }) {
  return (
    <div className={`setup-card card ${done ? 'is-done' : ''}`}>
      <div className="setup-card__header">
        <span className="setup-card__icon">
          <Icon />
        </span>
        <span className={`badge ${done ? 'badge--verified' : 'badge--pending'}`}>
          {done ? '✓ Done' : 'Not started'}
        </span>
      </div>
      <h3>{title}</h3>
      <p className="muted">{description}</p>
      {meta && <p className="setup-card__meta">{meta}</p>}
      <Link to={to} className={done ? 'btn-secondary' : 'btn-primary'}>
        {done ? doneLabel : actionLabel}
      </Link>
    </div>
  );
}

/**
 * Student dashboard — a two-step setup checklist (resume + GitHub) that
 * gates whether a recruiter has anything to score (FR 8, feeds FR 41-46).
 */
export default function StudentDashboard() {
  const { user } = useAuth();
  const firstName = user.firstName || 'there';

  const [resume, setResume] = useState(null);
  const [github, setGithub] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [r, g] = await Promise.allSettled([resumeApi.status(), githubApi.status()]);
      if (r.status === 'fulfilled') setResume(r.value);
      if (g.status === 'fulfilled') setGithub(g.value);
      setLoading(false);
    })();
  }, []);

  const resumeDone = Boolean(resume?.uploaded);
  const githubDone = Boolean(github?.connected);
  const allDone = resumeDone && githubDone;
  const stepsDone = Number(resumeDone) + Number(githubDone);

  return (
    <DashboardLayout>
      <h1 className="page-title">Welcome back, {firstName}!</h1>
      <p className="page-subtitle">
        Upload your resume and connect GitHub so we can analyse your job
        readiness.
      </p>

      {!loading && (
        <div className={`setup-banner ${allDone ? 'setup-banner--done' : ''}`}>
          <span className="setup-banner__icon">{allDone ? '✓' : stepsDone}</span>
          <span>
            {allDone ? (
              <>
                <strong>Your profile is complete.</strong> Recruiters can now
                see your verified skills and readiness score.
              </>
            ) : (
              <>
                <strong>{stepsDone} of 2 steps complete.</strong> Finish the
                setup below so recruiters have evidence to review.
              </>
            )}
          </span>
        </div>
      )}

      <div className="setup-grid">
        <SetupCard
          Icon={ResumeIcon}
          done={resumeDone}
          title="Upload Resume"
          description="We extract the skills you claim from a PDF resume."
          doneLabel="Replace resume"
          actionLabel="Upload Resume"
          to="/student/resume"
          meta={resumeDone ? resume.filename : null}
        />
        <SetupCard
          Icon={GithubMiningIcon}
          done={githubDone}
          title="Connect GitHub"
          description="We verify your claimed skills against real repository evidence."
          doneLabel="Manage connection"
          actionLabel="Connect GitHub Account"
          to="/student/github"
          meta={githubDone ? `@${github.username}` : null}
        />
      </div>
    </DashboardLayout>
  );
}
