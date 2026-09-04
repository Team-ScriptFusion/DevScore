import { ROLES, toPublicUser, listUsersByIds, findById } from '../models/User.js';
import { JOB_STATUSES, listJobsByRecruiter } from '../models/Job.js';
import {
  listApplicationsByJobIds,
  listApplicationsForStudentInJobs,
} from '../models/JobApplication.js';
import * as GithubConnection from '../models/GithubConnection.js';
import * as Resume from '../models/Resume.js';
import * as ReadinessReport from '../models/ReadinessReport.js';

/** Assemble the evidence summary a recruiter is allowed to see for one candidate. */
function buildCandidateSummary(user, connection, resume, skills, readiness) {
  const u = toPublicUser(user);
  return {
    id: u.id,
    name: u.fullName || u.email,
    email: u.email,
    avatarUrl: u.avatarUrl,
    resumeVerified: Boolean(resume),
    resumeFilename: resume?.original_name || null,
    resumeUploadedAt: resume?.uploaded_at || null,
    githubVerified: Boolean(connection),
    githubUsername: connection?.username || null,
    githubConnectedAt: connection?.connected_at || null,
    joinedAt: u.createdAt,
    skillsStatus: resume?.extraction_status || null,
    claimedSkills: skills?.byCategory || null,
    skillsUncategorized: skills?.uncategorized || null,
    readinessStatus: readiness?.status || null,
    readinessScore: readiness?.score ?? null,
    readinessBand: readiness?.band || null,
  };
}

/**
 * Candidates who applied to one of the calling recruiter's postings (FR 47/48).
 *
 * Scoped deliberately: a recruiter sees applicants, not every student on the
 * platform. A recruiter with no postings therefore sees an empty list — the
 * client distinguishes that from "no applicants yet".
 *
 * Returns ONE ROW PER APPLICATION, so a student who applied to two of this
 * recruiter's roles appears under each. That is what makes the per-role filter
 * and the "Applied For" column truthful, and it means `stats.total` (unique
 * students) and `stats.applications` (row count) are different numbers.
 *
 * `?jobId=` narrows to a single posting; one that isn't theirs reads as absent.
 */
export async function listCandidates(req, res, next) {
  try {
    const jobs = await listJobsByRecruiter(req.user.id);

    const jobFilter = (req.query?.jobId || '').trim();
    let scoped = jobs;
    if (jobFilter) {
      scoped = jobs.filter((j) => j.id === jobFilter);
      if (scoped.length === 0) {
        return res.status(404).json({ error: 'Job not found' });
      }
    }

    const jobIds = scoped.map((j) => j.id);
    const applications = jobIds.length ? await listApplicationsByJobIds(jobIds) : [];
    const studentIds = [...new Set(applications.map((a) => a.student_id))];
    const rows = studentIds.length ? await listUsersByIds(studentIds) : [];

    const [connections, resumes] = await Promise.all([
      GithubConnection.findByUserIds(studentIds),
      Resume.findByUserIds(studentIds),
    ]);
    const connectionByUser = Object.fromEntries(connections.map((c) => [c.user_id, c]));
    const resumeByUser = Object.fromEntries(resumes.map((r) => [r.user_id, r]));
    const skillsByResume = await Resume.getSkillsForResumes(resumes.map((r) => r.id));
    const readinessByResume = await ReadinessReport.findByResumeIds(resumes.map((r) => r.id));

    const studentById = new Map(rows.map((r) => [r.id, r]));
    const titleById = new Map(jobs.map((j) => [j.id, j.title]));

    const candidates = applications
      .filter((a) => studentById.has(a.student_id))
      .map((a) => {
        const student = studentById.get(a.student_id);
        const resume = resumeByUser[student.id];
        return {
          ...buildCandidateSummary(
            student,
            connectionByUser[student.id],
            resume,
            resume ? skillsByResume[resume.id] : null,
            resume ? readinessByResume[resume.id] : null,
          ),
          applicationId: a.id,
          jobId: a.job_id,
          jobTitle: titleById.get(a.job_id) || '',
          appliedAt: a.applied_at,
        };
      });

    res.json({
      candidates,
      jobs: jobs.map((j) => ({
        id: j.id,
        title: j.title,
        status: j.status,
        applicantCount: applications.filter((a) => a.job_id === j.id).length,
      })),
      stats: {
        total: rows.length,
        profileComplete: rows.filter(
          (r) => Boolean(resumeByUser[r.id]) && Boolean(connectionByUser[r.id]),
        ).length,
        applications: candidates.length,
        openJobs: jobs.filter((j) => j.status === JOB_STATUSES.OPEN).length,
      },
    });
  } catch (err) {
    next(err);
  }
}

/**
 * A single candidate's profile detail (FR 47/48 "candidate profile detail"),
 * restricted to candidates who applied to one of the calling recruiter's roles.
 *
 * A student who never applied is reported as 404 rather than 403 so a recruiter
 * cannot probe which student ids exist.
 */
export async function getCandidate(req, res, next) {
  try {
    const user = await findById(req.params.id);
    if (!user || user.role !== ROLES.STUDENT) {
      return res.status(404).json({ error: 'Candidate not found' });
    }

    const jobs = await listJobsByRecruiter(req.user.id);
    const jobIds = jobs.map((j) => j.id);
    const applications = jobIds.length
      ? await listApplicationsForStudentInJobs(user.id, jobIds)
      : [];
    if (applications.length === 0) {
      return res.status(404).json({ error: 'Candidate not found' });
    }

    const [connection, resume] = await Promise.all([
      GithubConnection.findByUserId(user.id),
      Resume.findByUserId(user.id),
    ]);
    const skills = resume ? await Resume.getSkills(resume.id) : null;
    const readiness = resume ? await ReadinessReport.findByResumeId(resume.id) : null;

    const titleById = new Map(jobs.map((j) => [j.id, j.title]));
    res.json({
      candidate: {
        ...buildCandidateSummary(user, connection, resume, skills, readiness),
        // Full breakdown/evidence/warnings, not just the flat status/score/band
        // above — the candidate detail view renders the whole readiness panel.
        readiness: ReadinessReport.toPublicReadinessReport(readiness),
        appliedRoles: applications.map((a) => ({
          jobId: a.job_id,
          jobTitle: titleById.get(a.job_id) || '',
          appliedAt: a.applied_at,
        })),
      },
    });
  } catch (err) {
    next(err);
  }
}
