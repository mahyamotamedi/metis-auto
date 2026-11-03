# Decision quality, first signal (jev-synth-v1)

100 SYNTHETIC requests, owner labels (60 tier 0 / 40 tier 1). Marker sent: False. Jev ran: True.

## Accuracy against the labels

| Slice | n | rules | rule_based | thx01 | jev | thx01_with_gate | jev_with_gate |
|---|---|---|---|---|---|---|---|
| all | 100 | 43% (43) | 59% (59) | 41% (41) | 72% (72) | 44% (44) | 70% (70) |
| persian | 70 | 41% (29) | 61% (43) | 39% (27) | 69% (48) | 43% (30) | 67% (47) |
| english | 15 | 47% (7) | 53% (8) | 47% (7) | 87% (13) | 47% (7) | 87% (13) |
| mixed | 15 | 47% (7) | 53% (8) | 47% (7) | 73% (11) | 47% (7) | 67% (10) |
| borderline | 5 | 40% (2) | 40% (2) | 40% (2) | 40% (2) | 40% (2) | 40% (2) |
| changed_by_owner | 0 | — | — | — | — | — | — |

## Errors by direction (all rows)

| Router | under-routed (label 1 → 0, quality risk) | over-routed (label 0 → 1, cost) | tier-1 recall | tier-0 recall | no decision |
|---|---|---|---|---|---|
| rules | 0 | 57 | 1.0 | 0.05 | 0 |
| rule_based | 35 | 6 | 0.125 | 0.9 | 0 |
| thx01 | 0 | 59 | 1.0 | 0.017 | 0 |
| jev | 1 | 27 | 0.975 | 0.55 | 0 |
| thx01_with_gate | 0 | 56 | 1.0 | 0.067 | 0 |
| jev_with_gate | 1 | 29 | 0.975 | 0.517 | 0 |

## Agreement between routers (tier 0/1)

- rules~rule_based: 14/100
- rules~thx01: 96/100
- rules~jev: 69/100
- rule_based~thx01: 12/100
- rule_based~jev: 41/100
- thx01~jev: 65/100
- all_three(rules, thx01, jev): 65/100
- all_three(rule_based, thx01, jev): 9/100

Gate (as configured): 14 rows decided by the fast gate {'gate.greeting': 3, 'gate.coding_intent': 11}.

## Accuracy by category

| Category | rules | rule_based | thx01 | jev | thx01_with_gate | jev_with_gate |
|---|---|---|---|---|---|---|
| code | 46% | 46% | 46% | 69% | 46% | 62% |
| factual | 29% | 64% | 29% | 79% | 29% | 71% |
| follow_up | 40% | 60% | 40% | 70% | 40% | 70% |
| greeting | 38% | 100% | 0% | 100% | 38% | 100% |
| math | 40% | 60% | 40% | 50% | 40% | 50% |
| reasoning | 90% | 10% | 90% | 90% | 90% | 90% |
| support | 36% | 71% | 36% | 43% | 36% | 43% |
| translation | 33% | 67% | 44% | 89% | 44% | 89% |
| writing | 42% | 58% | 42% | 75% | 42% | 75% |

## thx01: status, cost, latency

- status {'answered': 100}; path {'fallback_safe_tier': 40, 'slow_local': 60}; failures none; version {'b323afcef149f9288a9d0daef4badd67b9b87c61': 100}
- accuracy where the model itself decided (not a fallback): 0.633 on 60 rows
- decide_ms {'n': 100, 'min': 3086.3233, 'p10': 3521.9506, 'p50': 4076.9136, 'p90': 5012.6351, 'max': 7312.5014}
- cost total 0 USD, per call 0; input tokens {'n': 100, 'min': 466, 'p10': 491, 'p50': 551, 'p90': 646, 'max': 756}

| Question | reported confidence (n, p10, p50, p90) | missing | probability strength (p10, p50, p90) |
|---|---|---|---|
| complexity | 100, 0.1213, 0.381, 0.7691 | 0 | 0.427, 0.6969, 0.9297 |
| needs_reasoning | 100, 0.5509, 0.7149, 0.9471 | 0 | 0.5509, 0.7149, 0.9471 |
| cheap_model_ok | 100, 0.5215, 0.5874, 0.736 | 0 | 0.5215, 0.5874, 0.736 |
| intent | 100, 0.3829, 0.7362, 0.95 | 0 | 0.445, 0.8584, 0.9841 |
| depends_on_history | 100, 0.5189, 0.7088, 0.8643 | 0 | 0.5189, 0.7088, 0.8643 |

## jev: status, cost, latency

- status {'answered': 100}; path {'slow_hosted': 85, 'fallback_safe_tier': 15}; failures none; version {'jev-1.14.0': 100}
- accuracy where the model itself decided (not a fallback): 0.847 on 85 rows
- decide_ms {'n': 100, 'min': 716.8643, 'p10': 787.7069, 'p50': 970.7185, 'p90': 1125.8064, 'max': 3783.0447}
- cost total 0.0032478600 USD, per call 0.0000324786; input tokens {'n': 100, 'min': 668, 'p10': 676, 'p50': 697, 'p90': 741, 'max': 765}

| Question | reported confidence (n, p10, p50, p90) | missing | probability strength (p10, p50, p90) |
|---|---|---|---|
| complexity | 100, 0.5, 0.83, 1.0 | 0 | 0.54, 0.84, 1.0 |
| needs_reasoning | 0, None, None, None | 100 | 0.58, 0.83, 0.93 |
| cheap_model_ok | 0, None, None, None | 100 | 0.59, 0.84, 0.95 |
| intent | 100, 0.74, 1.0, 1.0 | 0 | 0.77, 1.0, 1.0 |
| depends_on_history | 0, None, None, None | 100 | 0.88, 0.95, 0.96 |

## Rows where at least one router missed the label

| id | lang | category | label | rules | rule_based | thx01 | jev | borderline |
|---|---|---|---|---|---|---|---|---|
| SYN-FA-001 | fa | greeting | 0 | 0 | 0 | 1 | 0 |  |
| SYN-FA-002 | fa | greeting | 0 | 0 | 0 | 1 | 0 |  |
| SYN-FA-003 | fa | greeting | 0 | 0 | 0 | 1 | 0 |  |
| SYN-FA-004 | fa | greeting | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-005 | fa | greeting | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-006 | fa | greeting | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-007 | fa | greeting | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-008 | fa | follow_up | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-009 | fa | follow_up | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-010 | fa | follow_up | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-011 | fa | follow_up | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-012 | fa | follow_up | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-013 | fa | follow_up | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-014 | fa | follow_up | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-015 | fa | follow_up | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-016 | fa | factual | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-017 | fa | factual | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-018 | fa | factual | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-019 | fa | factual | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-020 | fa | factual | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-021 | fa | factual | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-022 | fa | factual | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-023 | fa | factual | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-024 | fa | factual | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-025 | fa | factual | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-026 | fa | support | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-027 | fa | support | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-028 | fa | support | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-029 | fa | support | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-030 | fa | support | 0 | 1 | 0 | 1 | 1 | yes |
| SYN-FA-031 | fa | support | 1 | 1 | 0 | 1 | 1 | yes |
| SYN-FA-032 | fa | support | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-033 | fa | support | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-034 | fa | support | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-035 | fa | support | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-036 | fa | translation | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-037 | fa | translation | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-038 | fa | translation | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-039 | fa | translation | 0 | 1 | 0 | 0 | 1 |  |
| SYN-FA-040 | fa | translation | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-041 | fa | translation | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-042 | fa | writing | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-043 | fa | writing | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-044 | fa | writing | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-045 | fa | writing | 1 | 1 | 0 | 1 | 0 |  |
| SYN-FA-046 | fa | writing | 0 | 1 | 0 | 1 | 1 | yes |
| SYN-FA-047 | fa | writing | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-048 | fa | writing | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-049 | fa | writing | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-050 | fa | writing | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-051 | fa | code | 0 | 1 | 1 | 1 | 0 |  |
| SYN-FA-052 | fa | code | 0 | 1 | 1 | 1 | 1 |  |
| SYN-FA-054 | fa | code | 0 | 1 | 0 | 1 | 0 |  |
| SYN-FA-056 | fa | code | 0 | 1 | 1 | 1 | 1 | yes |
| SYN-FA-057 | fa | code | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-058 | fa | math | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-059 | fa | math | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-060 | fa | math | 1 | 1 | 0 | 1 | 1 | yes |
| SYN-FA-061 | fa | math | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-062 | fa | math | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-063 | fa | math | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-064 | fa | math | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-065 | fa | reasoning | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-066 | fa | reasoning | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-067 | fa | reasoning | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-068 | fa | reasoning | 0 | 1 | 0 | 1 | 1 |  |
| SYN-FA-069 | fa | reasoning | 1 | 1 | 0 | 1 | 1 |  |
| SYN-FA-070 | fa | reasoning | 1 | 1 | 0 | 1 | 1 |  |
| SYN-EN-001 | en | greeting | 0 | 1 | 0 | 1 | 0 |  |
| SYN-EN-002 | en | follow_up | 0 | 1 | 0 | 1 | 0 |  |
| SYN-EN-003 | en | factual | 0 | 1 | 0 | 1 | 0 |  |
| SYN-EN-004 | en | factual | 1 | 1 | 0 | 1 | 1 |  |
| SYN-EN-005 | en | support | 0 | 1 | 0 | 1 | 1 |  |
| SYN-EN-006 | en | support | 1 | 1 | 0 | 1 | 1 |  |
| SYN-EN-007 | en | translation | 0 | 1 | 0 | 1 | 0 |  |
| SYN-EN-008 | en | writing | 0 | 1 | 0 | 1 | 0 |  |
| SYN-EN-009 | en | writing | 1 | 1 | 0 | 1 | 1 |  |
| SYN-EN-010 | en | code | 0 | 1 | 1 | 1 | 1 |  |
| SYN-EN-012 | en | math | 0 | 1 | 0 | 1 | 0 |  |
| SYN-EN-013 | en | math | 1 | 1 | 0 | 1 | 1 |  |
| SYN-EN-014 | en | reasoning | 1 | 1 | 0 | 1 | 1 |  |
| SYN-EN-015 | en | reasoning | 1 | 1 | 0 | 1 | 1 |  |
| SYN-MI-001 | mixed | follow_up | 1 | 1 | 0 | 1 | 1 |  |
| SYN-MI-002 | mixed | factual | 0 | 1 | 1 | 1 | 0 |  |
| SYN-MI-003 | mixed | factual | 0 | 1 | 0 | 1 | 1 |  |
| SYN-MI-004 | mixed | support | 0 | 1 | 0 | 1 | 0 |  |
| SYN-MI-006 | mixed | translation | 0 | 1 | 0 | 1 | 0 |  |
| SYN-MI-007 | mixed | translation | 1 | 1 | 0 | 1 | 1 |  |
| SYN-MI-008 | mixed | writing | 0 | 1 | 0 | 1 | 1 |  |
| SYN-MI-009 | mixed | code | 0 | 1 | 1 | 1 | 1 |  |
| SYN-MI-011 | mixed | code | 1 | 1 | 0 | 1 | 1 |  |
| SYN-MI-012 | mixed | code | 0 | 1 | 0 | 1 | 0 |  |
| SYN-MI-013 | mixed | math | 0 | 1 | 0 | 1 | 1 |  |
| SYN-MI-014 | mixed | reasoning | 1 | 1 | 0 | 1 | 1 |  |
| SYN-MI-015 | mixed | reasoning | 1 | 1 | 0 | 1 | 1 |  |

## Limits

- SYNTHETIC requests written for this check, not real traffic: lengths, topics and phrasing differ from the dataset.
- Labels are one person's judgement (the owner); no second rater, no agreement measure.
- n = 100 (70 / 15 / 15 by language; 5 borderline): per-language and per-category numbers rest on 15 or fewer rows each.
- Tier 0/1 only: router tiers >= 1 count as 1. Accuracy is against labels, not answer quality.
- Models asked with the gate off and offline settings (no inline deadline, no router cache, confidence gate off).
- A first signal, not proof.
