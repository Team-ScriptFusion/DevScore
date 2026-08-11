import { ROLES, toPublicUser, listUsersByRole, findById } from '../models/User.js';

/** Shape a student row into the evidence summary a recruiter is allowed to see. */
function toCandidateSummary(row) {
  const u = toPublicUser(row);
  return {
    id: u.id,
    name: u.fullName || u.email,
    email: u.email,
    avatarUrl: u.avatarUrl,
    resumeVerified: Boolean(u.resumeFilename),
    resumeFilename: u.resumeFilename,
    resumeUploadedAt: u.resumeUploadedAt,
    githubVerified: Boolean(u.githubUsername),
    githubUsername: u.githubUsername,
    githubConnectedAt: u.githubConnectedAt,
    joinedAt: u.createdAt,
    skillsStatus: u.skillsExtractionStatus,
    claimedSkills: u.claimedSkills,
    skillsUncategorized: u.skillsUncategorized,
  };
}

/** List every candidate (student) with resume/GitHub verification status (FR 47/48). */
export async function listCandidates(req, res, next) {
  try {
    const rows = await listUsersByRole(ROLES.STUDENT);
    const candidates = rows.map(toCandidateSummary);
    res.json({
      candidates,
      stats: {
        total: candidates.length,
        profileComplete: candidates.filter((c) => c.resumeVerified && c.githubVerified).length,
      },
    });
  } catch (err) {
    next(err);
  }
}

/** A single candidate's profile detail (FR 47/48 "candidate profile detail"). */
export async function getCandidate(req, res, next) {
  try {
    const row = await findById(req.params.id);
    if (!row || row.role !== ROLES.STUDENT) {
      return res.status(404).json({ error: 'Candidate not found' });
    }
    res.json({ candidate: toCandidateSummary(row) });
  } catch (err) {
    next(err);
  }
}
