import { useLayoutEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useAuth, ROLE_HOME } from '../context/AuthContext.jsx';
import {
  ResumeIcon,
  GithubMiningIcon,
  ScoreIcon,
  EvidenceGapIcon,
} from '../components/FeatureIcons.jsx';
import './Home.css';

gsap.registerPlugin(ScrollTrigger);

const SKILL_STATUS = {
  verified: { label: 'Verified', fg: '#16a34a', bg: '#dcfce7' },
  partial: { label: 'Partial', fg: '#b45309', bg: '#fef3c7' },
  unverified: { label: 'Unverified', fg: '#dc2626', bg: '#fee2e2' },
};

const HERO_SKILLS = [
  { name: 'React', status: 'verified' },
  { name: 'Node.js', status: 'verified' },
  { name: 'PostgreSQL', status: 'verified' },
  { name: 'Docker', status: 'partial' },
  { name: 'GraphQL', status: 'unverified' },
];

const SIGNALS = ['Public repositories', 'Languages', 'Commit history', 'Contributions', 'Resume claims'];

const FEATURES = [
  {
    title: 'Resume skill extraction',
    body: 'An NLP module reads your resume and pulls out a structured set of the languages, frameworks and tools you claim.',
    Icon: ResumeIcon,
  },
  {
    title: 'GitHub evidence mining',
    body: 'We mine your public repositories, languages, commits and contribution history to see what you have actually shipped.',
    Icon: GithubMiningIcon,
  },
  {
    title: 'Weighted readiness score',
    body: 'A weighted engine cross-references your claims against evidence to produce a single, explainable 0-100 score.',
    Icon: ScoreIcon,
  },
  {
    title: 'Evidence gap dashboard',
    body: 'A clear breakdown of verified vs. unverified skills — so recruiters see substance, not a resume taken on faith.',
    Icon: EvidenceGapIcon,
  },
];

const STEPS = [
  { step: '01', title: 'Sign in with Google', body: 'No passwords. Create your account in a single click.' },
  { step: '02', title: 'Connect & upload', body: 'Link a public GitHub account and upload your resume.' },
  { step: '03', title: 'We verify', body: 'Your claimed skills are matched against real repository evidence.' },
  { step: '04', title: 'Share your score', body: 'Send recruiters an evidence-backed readiness score and breakdown.' },
];

const POINTS = [
  'Only your public repositories are analysed — nothing private is touched.',
  'Every score is explainable, down to the commits behind each skill.',
  'Your score stays private until you choose to share it.',
];

const BREAKDOWN = [
  { name: 'JavaScript / React', label: 'Verified', fg: '#16a34a', pct: 94 },
  { name: 'Node.js / Express', label: 'Verified', fg: '#16a34a', pct: 88 },
  { name: 'PostgreSQL', label: 'Verified', fg: '#16a34a', pct: 76 },
  { name: 'Docker', label: 'Partial evidence', fg: '#b45309', pct: 42 },
  { name: 'GraphQL', label: 'Unverified', fg: '#dc2626', pct: 12 },
];

function BrandMark({ height = 30 }) {
  return (
    <img
      src="/brand/devscore-logo-black.png"
      alt="DevScore"
      style={{ height, width: 'auto', display: 'block' }}
    />
  );
}

function ArrowRightIcon({ color = '#fff', size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function GithubMiniIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 3a9 9 0 0 0-2.85 17.54c.45.08.61-.2.61-.43v-1.68c-2.5.55-3.03-1.07-3.03-1.07-.41-1.04-1-1.32-1-1.32-.82-.56.06-.55.06-.55.9.06 1.38.93 1.38.93.8 1.38 2.11.98 2.62.75.08-.58.32-.98.57-1.2-2-.23-4.1-1-4.1-4.44 0-.98.35-1.78.92-2.41-.09-.23-.4-1.15.09-2.39 0 0 .75-.24 2.46.92a8.4 8.4 0 0 1 4.48 0c1.71-1.16 2.46-.92 2.46-.92.49 1.24.18 2.16.09 2.39.57.63.92 1.43.92 2.41 0 3.45-2.11 4.2-4.12 4.43.33.28.62.85.62 1.71v2.53c0 .24.16.51.62.43A9 9 0 0 0 12 3Z"
        stroke="#525252"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ShieldCheckIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3Z" stroke="#525252" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M9 12l2 2 4-4" stroke="#525252" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CheckCircleIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 12l5 5 9-10" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Home() {
  const { user, status } = useAuth();
  const isAuthed = status === 'authed' && user;
  const dashboardHref = isAuthed ? ROLE_HOME[user.role] || '/student' : null;
  const primaryHref = isAuthed ? dashboardHref : '/signup';
  const primaryLabel = isAuthed ? 'Go to Dashboard' : 'Get your score — free';

  const rootRef = useRef(null);
  const scoreValueRef = useRef(null);
  const scoreRingRef = useRef(null);

  useLayoutEffect(() => {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return undefined;

    const ctx = gsap.context(() => {
      // Hero — staggered reveal, above the fold so it runs immediately rather
      // than on a scroll trigger.
      gsap
        .timeline({ defaults: { ease: 'power3.out', duration: 0.7 } })
        .from('.home-hero__badge', { opacity: 0, y: 16 })
        .from('.home-hero h1', { opacity: 0, y: 22 }, '-=0.5')
        .from('.home-hero__lead', { opacity: 0, y: 18 }, '-=0.5')
        .from('.home-hero__actions .home-btn', { opacity: 0, y: 14, stagger: 0.1 }, '-=0.45')
        .from('.home-hero__trust span', { opacity: 0, y: 10, stagger: 0.08 }, '-=0.35')
        .from('.home-hero__visual', { opacity: 0, x: 32, duration: 0.8 }, '-=0.6');

      // Readiness-score number and ring fill count up together once the hero
      // has mostly settled.
      if (scoreValueRef.current) {
        scoreValueRef.current.textContent = '0';
        if (scoreRingRef.current) {
          scoreRingRef.current.style.background = 'conic-gradient(#0d9488 0 0%, #eeeeee 0% 100%)';
        }
        const counter = { value: 0 };
        gsap.to(counter, {
          value: 82,
          duration: 1.1,
          delay: 0.9,
          ease: 'power1.out',
          onUpdate: () => {
            const pct = Math.round(counter.value);
            if (scoreValueRef.current) scoreValueRef.current.textContent = pct;
            if (scoreRingRef.current) {
              scoreRingRef.current.style.background =
                `conic-gradient(#0d9488 0 ${pct}%, #eeeeee ${pct}% 100%)`;
            }
          },
        });
      }

      // Everything below the fold fades up as it's scrolled into view.
      gsap.from('.home-trust__label, .home-trust__items span', {
        opacity: 0,
        y: 10,
        stagger: 0.05,
        scrollTrigger: { trigger: '.home-trust', start: 'top 85%' },
      });

      gsap.from('.home-feature-card', {
        opacity: 0,
        y: 26,
        stagger: 0.12,
        duration: 0.6,
        ease: 'power2.out',
        scrollTrigger: { trigger: '.home-features', start: 'top 82%' },
      });

      gsap.utils.toArray('.home-section__intro, .home-how__intro, .home-report__eyebrow').forEach((el) => {
        gsap.from(el, {
          opacity: 0,
          y: 20,
          duration: 0.6,
          ease: 'power2.out',
          scrollTrigger: { trigger: el, start: 'top 85%' },
        });
      });

      gsap.from('.home-step', {
        opacity: 0,
        y: 24,
        stagger: 0.12,
        duration: 0.6,
        ease: 'power2.out',
        scrollTrigger: { trigger: '.home-steps', start: 'top 80%' },
      });

      gsap.from('.home-report__point', {
        opacity: 0,
        x: -16,
        stagger: 0.1,
        duration: 0.5,
        ease: 'power2.out',
        scrollTrigger: { trigger: '.home-report__points', start: 'top 85%' },
      });

      gsap.from('.evidence-card', {
        opacity: 0,
        y: 24,
        duration: 0.6,
        ease: 'power2.out',
        scrollTrigger: { trigger: '.evidence-card', start: 'top 85%' },
      });

      // Evidence bars fill from 0 to their real width on scroll, reusing the
      // width React already set inline as the animation's target.
      gsap.utils.toArray('.evidence-bar__fill').forEach((bar) => {
        const target = bar.style.width;
        gsap.fromTo(
          bar,
          { width: '0%' },
          {
            width: target,
            duration: 0.9,
            ease: 'power2.out',
            scrollTrigger: { trigger: bar, start: 'top 90%' },
          },
        );
      });

      gsap.from('.home-cta__box', {
        opacity: 0,
        scale: 0.96,
        duration: 0.6,
        ease: 'power2.out',
        scrollTrigger: { trigger: '.home-cta__box', start: 'top 85%' },
      });
    }, rootRef);

    return () => ctx.revert();
  }, []);

  return (
    <div className="home" ref={rootRef}>
      <header className="home-header">
        <span className="home-brand">
          <BrandMark />
        </span>
        <nav className="home-nav">
          <a href="#features">Features</a>
          <a href="#how">How it works</a>
          <a href="#report">Your report</a>
        </nav>
        <div className="home-actions">
          {isAuthed ? (
            <Link to={dashboardHref} className="home-btn home-btn--primary">
              Go to Dashboard
            </Link>
          ) : (
            <>
              <Link to="/login" className="home-link">Log in</Link>
              <Link to="/signup" className="home-btn home-btn--primary">
                Get your score
              </Link>
            </>
          )}
        </div>
      </header>

      <main>
        {/* HERO */}
        <section className="home-hero">
          <div>
            <span className="home-hero__badge">
              <span className="home-hero__dot" />For job-seeking developers
            </span>
            <h1>Turn your GitHub into proof recruiters trust.</h1>
            <p className="home-hero__lead">
              Stop hoping a bullet point lands. DevScore reads your resume, mines your public
              repositories, and turns your real, shipped work into a transparent 0&ndash;100
              readiness score.
            </p>
            <div className="home-hero__actions">
              <Link to={primaryHref} className="home-btn home-btn--primary">
                {primaryLabel}
                <ArrowRightIcon />
              </Link>
              <a href="#how" className="home-btn home-btn--secondary">See how it works</a>
            </div>
            <div className="home-hero__trust">
              <span><GithubMiniIcon />Public repos only</span>
              <span><ShieldCheckIcon />Your score stays private</span>
            </div>
          </div>

          <div className="home-hero__visual">
            <div className="home-hero__glow" />
            <div className="report-card">
              <div className="report-card__top">
                <div className="report-card__person">
                  <span className="report-card__avatar">AR</span>
                  <div>
                    <div className="report-card__name">Amara Rao</div>
                    <div className="report-card__role">Full-stack · @amara-dev</div>
                  </div>
                </div>
                <span className="report-card__pill">Readiness</span>
              </div>
              <div className="report-card__score-row">
                <div
                  className="report-card__ring"
                  ref={scoreRingRef}
                  style={{ background: 'conic-gradient(#0d9488 0 82%, #eeeeee 82% 100%)' }}
                >
                  <div className="report-card__ring-inner">
                    <span className="report-card__score-value" ref={scoreValueRef}>82</span>
                  </div>
                </div>
                <div>
                  <div className="report-card__verdict">Strong candidate</div>
                  <div className="report-card__desc">9 of 11 claimed skills verified against real repository evidence.</div>
                </div>
              </div>
              <div className="report-card__skills">
                {HERO_SKILLS.map((s) => {
                  const st = SKILL_STATUS[s.status];
                  return (
                    <div className="report-card__skill" key={s.name}>
                      <span className="report-card__skill-name">{s.name}</span>
                      <span className="skill-pill" style={{ background: st.bg, color: st.fg }}>
                        <span className="skill-pill__dot" style={{ background: st.fg }} />{st.label}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </section>

        {/* TRUST STRIP */}
        <section className="home-trust">
          <div className="home-trust__inner">
            <span className="home-trust__label">Signals we read</span>
            <div className="home-trust__items">
              {SIGNALS.map((sig) => <span key={sig}>{sig}</span>)}
            </div>
          </div>
        </section>

        {/* FEATURES */}
        <section id="features" className="home-section">
          <div className="home-section__intro">
            <span className="home-section__eyebrow">WHAT DEVSCORE DOES</span>
            <h2>Everything you need to make your resume undeniable.</h2>
            <p>Built to close the verification gap between what you say you can do and what you&rsquo;ve actually shipped.</p>
          </div>
          <div className="home-features">
            {FEATURES.map(({ title, body, Icon }) => (
              <div className="home-feature-card" key={title}>
                <span className="home-feature-card__icon"><Icon /></span>
                <h3>{title}</h3>
                <p>{body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* HOW IT WORKS */}
        <section id="how" className="home-how">
          <div className="home-how__inner">
            <div className="home-how__intro">
              <span className="home-section__eyebrow home-section__eyebrow--dark">FOUR STEPS</span>
              <h2>From sign-up to shareable score in minutes.</h2>
            </div>
            <div className="home-steps">
              {STEPS.map((s) => (
                <div className="home-step" key={s.step}>
                  <span className="home-step__num">{s.step}</span>
                  <h3>{s.title}</h3>
                  <p>{s.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* REPORT SHOWCASE */}
        <section id="report" className="home-report">
          <div>
            <span className="home-report__eyebrow">EVIDENCE, NOT ASSERTIONS</span>
            <h2>See exactly which skills are backed by code.</h2>
            <p>
              Every claimed skill is matched against languages, commits and repositories in your
              GitHub history. You get a transparent breakdown &mdash; verified, needs more evidence,
              or unverified &mdash; and so does every recruiter you share it with.
            </p>
            <div className="home-report__points">
              {POINTS.map((p) => (
                <div className="home-report__point" key={p}>
                  <span className="home-report__check"><CheckCircleIcon /></span>
                  <span>{p}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="evidence-card">
            <div className="evidence-card__header">
              <span className="evidence-card__title">Skill evidence breakdown</span>
              <span className="evidence-card__count">11 claimed skills</span>
            </div>
            <div className="evidence-card__list">
              {BREAKDOWN.map((b) => (
                <div key={b.name}>
                  <div className="evidence-row__top">
                    <span className="evidence-row__name">{b.name}</span>
                    <span className="evidence-row__label" style={{ color: b.fg }}>{b.label}</span>
                  </div>
                  <div className="evidence-bar">
                    <div className="evidence-bar__fill" style={{ background: b.fg, width: `${b.pct}%` }} />
                  </div>
                </div>
              ))}
            </div>
            <div className="evidence-card__legend">
              <span><i style={{ background: '#16a34a' }} />Verified</span>
              <span><i style={{ background: '#b45309' }} />Partial evidence</span>
              <span><i style={{ background: '#dc2626' }} />Unverified</span>
            </div>
          </div>
        </section>

        {/* FINAL CTA */}
        <section className="home-cta">
          <div className="home-cta__box">
            <div className="home-cta__decor home-cta__decor--1" />
            <div className="home-cta__decor home-cta__decor--2" />
            <div className="home-cta__content">
              <h2>Let your code do the talking.</h2>
              <p>Connect GitHub, upload your resume, and get an evidence-backed readiness score you can put in front of any recruiter.</p>
              <Link to={primaryHref} className="home-btn home-btn--white">
                {primaryLabel}
                <ArrowRightIcon color="#0f766e" size={17} />
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="home-footer">
        <div className="home-footer__inner">
          <span className="home-footer__brand">
            <BrandMark height={22} />
          </span>
          <nav className="home-footer__nav">
            <a href="#features">Features</a>
            <a href="#how">How it works</a>
            <a href="#report">Your report</a>
            <Link to="/login">Log in</Link>
          </nav>
          <span className="home-footer__copy">© {new Date().getFullYear()} DevScore — Team ScriptFusion</span>
        </div>
      </footer>
    </div>
  );
}
