import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import DashboardLayout from '../components/DashboardLayout.jsx';
import PageHeader from '../components/PageHeader.jsx';
import SkillChips from '../components/SkillChips.jsx';
import EmptyState from '../components/EmptyState.jsx';
import Meter from '../components/Meter.jsx';
import ScoreRing, { ScoreRingEmpty } from '../components/ScoreRing.jsx';
import { SkeletonCards } from '../components/Skeleton.jsx';
import useReveal from '../hooks/useReveal.js';
import { useAuth } from '../context/AuthContext.jsx';
import { githubApi, jobsApi, resumeApi } from '../lib/api.js';
import { relativeDate, absoluteDate } from '../lib/format.js';
import { ResumeIcon, GithubMiningIcon } from '../components/FeatureIcons.jsx';
import {
  BriefcaseIcon,
  CheckIcon,
  ChevronRightIcon,
  SparkIcon,
} from '../components/DashboardIcons.jsx';

// Scoring runs in the background (semantic_engine) and can take tens of
// seconds, so poll while it's in flight rather than making the student refresh.
const READINESS_POLL_MS = 4000;

/**
 * A locked card still links through — the job-role gate is an ordering hint,
 * not an access control. The routes stay reachable and the server never
 * rejects an upload for a missing application.
 *
 * `isNext` marks the single step the student should do now; it's the only teal
 * frame in the row, so the eye lands on it without reading all three.
 */
function SetupCard({
  step, Icon, done, locked = false, isNext = false, title, description,
  doneLabel, actionLabel, lockedHint, to, meta,
}) {
  const state = [
    'setup-card card',
    done ? 'is-done' : '',
    locked ? 'is-locked' : '',
    isNext ? 'is-next' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={state}>
      <div className="setup-card__header">
        <span className="setup-card__icon">
          <Icon />
        </span>
        <span className={`badge ${done ? 'badge--verified' : 'badge--pending'}`}>
          {done ? 'Done' : locked ? 'Locked' : 'Not started'}
        </span>
      </div>
      <div className="setup-card__title-row">
        <span className="setup-card__step" aria-hidden="true">
          {done ? <CheckIcon size={13} /> : step}
        </span>
        <h3>{title}</h3>
      </div>
      <p className="muted">{description}</p>
      {locked && <p className="setup-card__hint">{lockedHint}</p>}
      {meta && <p className="setup-card__meta">{meta}</p>}
      <Link to={to} className={done || locked ? 'btn-secondary' : 'btn-primary'}>
        {done ? doneLabel : actionLabel}
      </Link>
    </div>
  );
}

/**
 * Headline readiness. The score data already rides along on `resumeApi.status()`
 * — it was being fetched and discarded here, leaving the student's single most
 * important number two clicks away on the Skills Status page.
 */
function ReadinessHero({ readiness, githubDone, resumeDone }) {
  const status = readiness?.status;

  if (status === 'success') {
    return (
      <div className="card readiness-hero">
        <ScoreRing value={readiness.score} size="lg" suffix="/100" label={`Job readiness ${readiness.score} out of 100`} />
        <div className="readiness-hero__body">
          <div className="readiness-hero__head">
            <h2 className="readiness-hero__title">Job Readiness</h2>
            <span className="badge badge--verified">Scored</span>
          </div>
          <p className="readiness-hero__band">
            Your profile reads as <strong>{readiness.band}</strong>. This is the
            number recruiters see beside your name.
          </p>
          {readiness.confidence != null && (
            <div className="readiness-hero__meter">
              <Meter
                value={Math.round(readiness.confidence * 100)}
                label="Evidence confidence"
                valueLabel={`${Math.round(readiness.confidence * 100)}%`}
              />
            </div>
          )}
          <div className="readiness-hero__actions">
            <Link to="/student/skills" className="btn-secondary">
              View full report
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (status === 'pending') {
    return (
      <div className="card readiness-hero">
        <ScoreRingEmpty size="lg" hint="…" />
        <div className="readiness-hero__body">
          <div className="readiness-hero__head">
            <h2 className="readiness-hero__title">Job Readiness</h2>
            <span className="badge badge--pending">Scoring</span>
          </div>
          <p className="readiness-hero__band">
            We&rsquo;re verifying your claimed skills against your GitHub
            activity. This can take up to a minute — the score appears here
            automatically.
          </p>
        </div>
      </div>
    );
  }

  if (status === 'failed') {
    return (
      <div className="card readiness-hero">
        <ScoreRingEmpty size="lg" />
        <div className="readiness-hero__body">
          <div className="readiness-hero__head">
            <h2 className="readiness-hero__title">Job Readiness</h2>
            <span className="badge badge--missing">Scoring failed</span>
          </div>
          <p className="readiness-hero__band">
            We couldn&rsquo;t score your GitHub evidence
            {readiness?.error ? ` (${readiness.error})` : ''}. Re-uploading your
            resume will start a fresh run.
          </p>
          <div className="readiness-hero__actions">
            <Link to="/student/resume" className="btn-secondary">
              Re-upload resume
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // Not scored yet — name the specific step that unlocks it.
  const missing = !resumeDone ? 'resume' : !githubDone ? 'github' : null;
  return (
    <div className="card readiness-hero">
      <ScoreRingEmpty size="lg" />
      <div className="readiness-hero__body">
        <div className="readiness-hero__head">
          <h2 className="readiness-hero__title">Job Readiness</h2>
          <span className="badge badge--neutral">Not scored yet</span>
        </div>
        <p className="readiness-hero__band">
          {missing === 'resume'
            ? 'Upload your resume so we know which skills you claim, then connect GitHub to verify them against real code.'
            : missing === 'github'
              ? 'Connect your GitHub account to verify your claimed skills against your actual repositories.'
              : 'Your score will appear here once we finish analysing your evidence.'}
        </p>
        {missing && (
          <div className="readiness-hero__actions">
            <Link
              to={missing === 'resume' ? '/student/resume' : '/student/github'}
              className="btn-primary"
            >
              {missing === 'resume' ? 'Upload Resume' : 'Connect GitHub'}
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Student dashboard — a three-step setup checklist (job role, resume, GitHub)
 * that gates whether a recruiter has anything to score (FR 8, feeds FR 41-46),
 * fronted by the readiness score those steps produce.
 * The role comes first: everything else is evidence measured against it.
 */
export default function StudentDashboard() {
  const { user } = useAuth();
  const firstName = user.firstName || 'there';

  const [resume, setResume] = useState(null);
  const [github, setGithub] = useState(null);
  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [r, g, a] = await Promise.allSettled([
        resumeApi.status(),
        githubApi.status(),
        jobsApi.listApplied(),
      ]);
      if (r.status === 'fulfilled') setResume(r.value);
      if (g.status === 'fulfilled') setGithub(g.value);
      if (a.status === 'fulfilled') setApplications(a.value.applications);
      setLoading(false);
    })();
  }, []);

  const readinessStatus = resume?.readiness?.status;

  // Keep polling only while scoring is actually in flight, mirroring SkillsStatus.
  useEffect(() => {
    if (readinessStatus !== 'pending') return undefined;
    const id = setInterval(async () => {
      try {
        setResume(await resumeApi.status());
      } catch {
        /* transient poll failure — try again next tick */
      }
    }, READINESS_POLL_MS);
    return () => clearInterval(id);
  }, [readinessStatus]);

  const roleDone = applications.length > 0;
  const resumeDone = Boolean(resume?.uploaded);
  const githubDone = Boolean(github?.connected);
  const allDone = roleDone && resumeDone && githubDone;
  const stepsDone = Number(roleDone) + Number(resumeDone) + Number(githubDone);

  // Exactly one card is "next": the first unfinished step in order.
  const nextStep = !roleDone ? 1 : !resumeDone ? 2 : !githubDone ? 3 : 0;

  const setupRef = useReveal([loading], { enabled: !loading });

  return (
    <DashboardLayout>
      <PageHeader
        title={`Welcome back, ${firstName}!`}
        subtitle="Pick the job roles you're applying for, then upload your resume and connect GitHub so we can analyse your job readiness."
        actions={
          <Link to="/student/jobs" className="btn-secondary">
            Browse roles
          </Link>
        }
      />

      {loading ? (
        <SkeletonCards n={1} />
      ) : (
        <>
          <ReadinessHero
            readiness={resume?.readiness}
            resumeDone={resumeDone}
            githubDone={githubDone}
          />

          <div className={`setup-banner ${allDone ? 'setup-banner--done' : ''}`}>
            <span className="setup-banner__icon">
              {allDone ? <CheckIcon size={16} /> : stepsDone}
            </span>
            <span>
              {allDone ? (
                <>
                  <strong>Your profile is complete.</strong> Recruiters can now
                  see your verified skills and readiness score.
                </>
              ) : (
                <>
                  <strong>{stepsDone} of 3 steps complete.</strong> Finish the
                  setup below so recruiters have evidence to review.
                </>
              )}
            </span>
          </div>
        </>
      )}

      <div className="setup-grid" ref={setupRef}>
        <SetupCard
          step={1}
          Icon={BriefcaseIcon}
          done={roleDone}
          isNext={nextStep === 1}
          title="Select a Job Role"
          description="Choose the roles you're applying for — everything else is evidence measured against them."
          doneLabel="Browse more roles"
          actionLabel="Browse Job Roles"
          to="/student/jobs"
          meta={
            roleDone
              ? `${applications.length} role${applications.length === 1 ? '' : 's'} selected`
              : null
          }
        />
        {/* locked only while still incomplete — a step finished before this
            feature shipped must never be drawn as locked */}
        <SetupCard
          step={2}
          Icon={ResumeIcon}
          done={resumeDone}
          locked={!roleDone && !resumeDone}
          isNext={nextStep === 2}
          lockedHint="Select a job role first."
          title="Upload Resume"
          description="We extract the skills you claim from a PDF resume."
          doneLabel="Replace resume"
          actionLabel="Upload Resume"
          to="/student/resume"
          meta={resumeDone ? resume.filename : null}
        />
        <SetupCard
          step={3}
          Icon={GithubMiningIcon}
          done={githubDone}
          locked={!roleDone && !githubDone}
          isNext={nextStep === 3}
          lockedHint="Select a job role first."
          title="Connect GitHub"
          description="We verify your claimed skills against real repository evidence."
          doneLabel="Manage connection"
          actionLabel="Connect GitHub Account"
          to="/student/github"
          meta={githubDone ? `@${github.username}` : null}
        />
      </div>

      {!loading && (
        <div className="card card--stack">
          <div className="card-head">
            <div>
              <h3>Roles You Applied To</h3>
              <p className="muted">
                Recruiters who posted these roles can see your profile.
              </p>
            </div>
            {roleDone && (
              <Link to="/student/jobs" className="btn-secondary">
                Manage roles
              </Link>
            )}
          </div>

          {roleDone ? (
            <ul className="applied-list">
              {applications.map((a) => (
                <li className="applied-list__item" key={a.id}>
                  <span className="applied-list__title">{a.job.title}</span>
                  <span className="applied-list__meta">
                    {a.job.location || 'Remote'} · applied{' '}
                    <span title={absoluteDate(a.appliedAt)}>
                      {relativeDate(a.appliedAt)}
                    </span>
                  </span>
                  {a.job.status === 'closed' && (
                    <span className="badge badge--neutral">Closed</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              Icon={BriefcaseIcon}
              compact
              title="No roles selected yet"
              description="Everything DevScore measures is scored against a specific role. Pick one to get started."
              action={
                <Link to="/student/jobs" className="btn-primary">
                  Browse Job Roles
                </Link>
              }
            />
          )}
        </div>
      )}

      {resumeDone && (
        <div className="card card--stack">
          <div className="card-head">
            <div>
              <h3>Your Claimed Skills</h3>
              <p className="muted">
                Extracted from your resume — this is what recruiters see.
              </p>
            </div>
            <Link to="/student/skills" className="btn-secondary">
              Full breakdown
              <ChevronRightIcon />
            </Link>
          </div>
          <SkillChips
            status={resume.skills?.status}
            byCategory={resume.skills?.byCategory}
            uncategorized={resume.skills?.uncategorized}
          />
        </div>
      )}

      {!loading && !resumeDone && roleDone && (
        <div className="card card--stack">
          <EmptyState
            Icon={SparkIcon}
            compact
            title="No skills extracted yet"
            description="Upload your resume and we'll pull out the skills you claim, then verify them against your GitHub."
            action={
              <Link to="/student/resume" className="btn-primary">
                Upload Resume
              </Link>
            }
          />
        </div>
      )}
    </DashboardLayout>
  );
}
