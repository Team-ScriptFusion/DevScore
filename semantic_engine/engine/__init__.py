"""
DevScore Engine — the evidence and scoring core of ScriptFusion's
AI-Driven Job Readiness Scoring System (Implementation 02).

Implementation 01 (Team-ScriptFusion/DevScore) already answers "what does
the resume claim?". This package answers the harder half:

    "Is that claim actually true, and how good is the code behind it?"

Pipeline:

    resume.pdf ──▶ resume.parser ──────▶ ClaimedSkill[]
                                              │
    github user ─▶ github.miner ──▶ RepoEvidence[]  ──▶ analysis.*  ──▶ CodeMetrics
                                              │                              │
                                              ▼                              ▼
                                     matching.semantic ──▶ SkillVerdict[] ◀───┘
                                              │
                                              ▼
                                      scoring.engine ──▶ ReadinessReport (0–100)

Every number in the final report traces back to a named repository, file
and metric — the "Evidence Gap" the recruiter dashboard renders is just a
projection of ReadinessReport.verdicts.
"""

__version__ = "0.2.0"
