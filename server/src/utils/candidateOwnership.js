import { ROLES, findById } from '../models/User.js';
import { listJobsByRecruiter } from '../models/Job.js';
import { listApplicationsForStudentInJobs } from '../models/JobApplication.js';

/**
 * True if `user` is a student who has at least one application among the
 * given `applications` — the ownership rule behind a recruiter viewing a
 * candidate's evidence (they must have applied to one of the recruiter's
 * postings).
 */
export function isOwnedCandidate(user, applications) {
  return Boolean(user) && user.role === ROLES.STUDENT && applications.length > 0;
}

/**
 * Resolves the student `studentId` if `recruiterId` may view their
 * evidence, else null. Callers should respond 404 (not 403) on null, so a
 * recruiter cannot probe which student ids exist.
 */
export async function findOwnedCandidate(recruiterId, studentId) {
  const user = await findById(studentId);
  const jobs = await listJobsByRecruiter(recruiterId);
  const jobIds = jobs.map((j) => j.id);
  const applications = jobIds.length
    ? await listApplicationsForStudentInJobs(studentId, jobIds)
    : [];
  return isOwnedCandidate(user, applications) ? user : null;
}
