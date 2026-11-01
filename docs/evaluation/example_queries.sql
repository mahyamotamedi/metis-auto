-- Example queries for golden-v1. All return counts or IDs, except the last two,
-- which return message text: run those only locally and never paste the output
-- anywhere (data licence, docs/evaluation/golden_v1.md).

-- Records per stratum value.
SELECT stratum->>'primary_intent' AS intent, stratum->>'cohort' AS cohort, count(*)
FROM eval.dataset_record WHERE dataset_id = 'golden-v1' GROUP BY 1, 2 ORDER BY 3 DESC;

-- Quotas, what was achieved, and any shortfall with its cause.
SELECT s.margin, s.key, s.population_n, s.quota, s.achieved, s.shortfall,
       s.redistribution_note
FROM eval.stratum_population s
JOIN eval.sampling_run r USING (sampling_run_id)
WHERE r.dataset_id = 'golden-v1' AND s.shortfall > 0;

-- History length per record.
SELECT c.record_id, count(*) AS earlier_messages
FROM eval.record_input_component c
WHERE c.kind = 'earlier_message' GROUP BY 1 ORDER BY 2 DESC;

-- Pairing flags over the whole population.
SELECT pair_flag, eligible, exclusion_reason, count(*)
FROM eval.request GROUP BY 1, 2, 3 ORDER BY 4 DESC;

-- Reviewer agreement: records with two reviewers on one dimension.
SELECT a.dimension, count(*) AS pairs,
       avg((a.value = b.value)::int) AS percent_agreement
FROM eval.annotation a
JOIN eval.annotation b
  ON a.record_id = b.record_id AND a.dimension = b.dimension
 AND a.annotator_pseudonym < b.annotator_pseudonym
WHERE a.method = 'human' AND b.method = 'human'
GROUP BY 1;

-- Records per bot and cohort.
SELECT q.owner_cohort, q.bot_id, count(*) AS records
FROM eval.dataset_record x JOIN eval.request q USING (request_id)
GROUP BY 1, 2 ORDER BY 3 DESC;

-- Reconciliation results of the latest ingest run.
SELECT check_name, expected, actual, ok FROM meta.reconciliation
WHERE run_id = (SELECT max(run_id) FROM meta.ingest_run) ORDER BY ok, check_name;

-- Current accepted label per record and dimension.
SELECT * FROM eval.record_current_label WHERE dimension = 'complexity';

-- LOCAL ONLY, returns text: the routing input of one record, without retrieval.
SELECT position, kind, role, availability_stage, content
FROM eval.routing_input_pre_retrieval_v1
WHERE record_id = :'record_id' ORDER BY position;

-- LOCAL ONLY, returns text: with the target answer's retrieved chunks.
SELECT position, kind, role, availability_stage, content
FROM eval.routing_input_post_retrieval_v1
WHERE record_id = :'record_id' ORDER BY position;
