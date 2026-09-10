import { supabase } from '../config/db.js';

/** Outputs of the scoring pipeline: frozen weights, computed WVR scores, validation stats. */

/** Replace-wholesale write of one weights_version's category rows. */
export async function saveWeights(weightsVersion, weights) {
  const rows = weights.map((w) => ({
    category: w.category,
    weight: w.weight,
    weights_version: weightsVersion,
  }));
  const { data, error } = await supabase.from('skill_weights').insert(rows).select();
  if (error) throw new Error(error.message);
  return data;
}

/** Read back one weights_version's category rows. */
export async function findWeights(weightsVersion) {
  const { data, error } = await supabase
    .from('skill_weights')
    .select('category, weight')
    .eq('weights_version', weightsVersion);
  if (error) throw new Error(error.message);
  return data;
}

/** Store one student's computed WVR score for a given weights_version. */
export async function saveWvrScore(userId, wvrScore, weightsVersion) {
  const { data, error } = await supabase
    .from('wvr_scores')
    .insert({ user_id: userId, wvr_score: wvrScore, weights_version: weightsVersion })
    .select()
    .single();
  if (error) throw new Error(error.message);
  return data;
}

/** Store this weights_version's validation metrics (spearman_rho, mae, inter_rater_alpha). */
export async function saveValidationResults(weightsVersion, results) {
  const rows = results.map((r) => ({
    weights_version: weightsVersion,
    metric_name: r.metric_name,
    metric_value: r.metric_value,
    sample_size: r.sample_size,
  }));
  const { data, error } = await supabase.from('validation_results').insert(rows).select();
  if (error) throw new Error(error.message);
  return data;
}
