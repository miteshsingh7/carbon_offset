Synthetic test: the claim of VCS 2469 was multiplied by fixed factors and the stored satellite band was scored again. These are not documented over-crediting cases. Precision and recall here describe the scoring rule on injected claims only.

### Injected Claims Evaluation Matrix

| Factor | Claimed Area (ha) | Status | Confidence | Discrepancy (%) | Central Shortfall (ha) | Low Shortfall (ha) | Detection Limit (%) | Band Span (%) |
| ---: | ---: | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 0.90 | 1170.00 | CONSISTENT | LOW | 0.00% | -95.00 | 154.80 | 13.23% | 41.92% |
| 1.00 | 1300.00 | CONSISTENT | LOW | 0.00% | 35.00 | 284.80 | 21.91% | 37.72% |
| 1.10 | 1430.00 | CONSISTENT | LOW | 0.00% | 165.00 | 414.80 | 29.01% | 34.30% |
| 1.25 | 1625.00 | CONSISTENT | LOW | 7.35% | 360.00 | 609.80 | 37.53% | 30.18% |
| 1.30 | 1690.00 | MINOR | LOW | 10.91% | 425.00 | 674.80 | 39.93% | 29.02% |
| 1.50 | 1950.00 | MINOR | LOW | 22.79% | 685.00 | 934.80 | 47.94% | 25.15% |
| 2.00 | 2600.00 | MAJOR | LOW | 42.09% | 1335.00 | 1584.80 | 60.95% | 18.86% |

### Classification Counts & Metrics

- True Positives (TP, factor > 1.00 and flagged): 3
- False Positives (FP, factor <= 1.00 and flagged): 0
- True Negatives (TN, factor <= 1.00 and consistent): 2
- False Negatives (FN, factor > 1.00 and consistent): 2
- Not flagged, not consistent: 0
- Precision: 1.0000
- Recall: 0.6000

### How to read this

1. The scoring rule is one-sided: it flags only a claim larger than obs_high / (1 - minor threshold). No claim at or below the stored claim can be flagged, so FP = 0 and precision = 1.0 follow from the rule, not from a tested behaviour.
2. The labels treat the stored claim of 1300.00 ha as the true area; that is not known.
3. Recall depends on the grid of factors used. The grid-independent result is the smallest claim that is flagged: 1672.91 ha (factor 1.2869), which is 28.69% above the stored claim and 11.11% above obs_high.
4. Every row has confidence LOW.

### Flag Threshold Analysis

- Smallest observed factor producing a flag: 1.30
- Analytically derived minimum claim for MINOR status: 1672.91 ha (factor 1.2869)
- Agreement status: Observed smallest flagged factor matches analytical threshold position on the factor grid

### Detection Limit Disclosure

The detection limit of the stored observation band is (claimed - obs_low) / claimed = 21.91% (284.80 ha) at the stated claim of 1300.00 ha.
