/**
 * Seeds expert_scores with SYNTHETIC rows for every existing student, so
 * this module's pipeline (split -> fit -> validate) has something to run
 * against. This is dev/test data ONLY — every row's expert_id is prefixed
 * "synthetic-" specifically so it can never be mistaken for real
 * industry-expert judgment in a query or a report (design spec section 2).
 *
 * Usage: node server/scripts/seedSyntheticExpertScores.js --confirm
 */
import { supabase } from '../src/config/db.js';
import { ROLES } from '../src/models/User.js';

const SYNTHETIC_EXPERT_ID = 'synthetic-v1';

function randomScore(seedable) {
  // Simple deterministic-ish spread (not cryptographic, not statistically
  // rigorous) — this only needs to be plausible enough to exercise the
  // pipeline's mechanics, per design spec section 2's scope.
  const hash = [...seedable].reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  return Math.round(((hash % 100) + 100) % 100 * 10) / 10;
}

async function main() {
  if (!process.argv.includes('--confirm')) {
    console.error('Refusing to run without --confirm. This writes SYNTHETIC data, not real expert scores.');
    process.exit(1);
  }

  const { data: students, error } = await supabase
    .from('users')
    .select('id')
    .eq('role', ROLES.STUDENT);
  if (error) throw new Error(error.message);

  if (students.length === 0) {
    console.log('No students found — nothing to seed.');
    return;
  }

  const rows = students.map((student) => ({
    user_id: student.id,
    expert_id: SYNTHETIC_EXPERT_ID,
    score: randomScore(student.id),
  }));

  const { error: insertError } = await supabase.from('expert_scores').insert(rows);
  if (insertError) throw new Error(insertError.message);

  console.log(`Seeded ${rows.length} SYNTHETIC expert_scores rows (expert_id="${SYNTHETIC_EXPERT_ID}").`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
