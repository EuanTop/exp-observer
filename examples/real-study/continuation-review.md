# Continuing the study from its evidence

A second agent resumed the exact-search experiment through scoped ExpObserver context. It did not need the original conversation. This stage reviewed existing measurements rather than running a new retrieval benchmark.

## Independent checks

The reviewer verified all 22 evidence files present at the start of the review, compared fixture identities and recomputed the retained answers using a separate ASCII regular-expression normalization and matching implementation. All **288 retained initial and updated answer lists** agreed. The queries affected by stale snapshots were also consistent across the three implementations.

Each latency CSV contained five batches of 48 queries in the expected order. The original program retained complete answers only for the final initial batch and the updated batch. Earlier correctness assertions cannot be independently reconstructed answer by answer from those files.

The original reference shared a tokenizer with the Python algorithms. It was an independent matching implementation, not independent normalization. This review adds an independent normalization check within the recorded ASCII input scope.

## Cost interpretation

The reviewer reproduced the reported medians. Combining fresh-build medians with the sum of the five measured query batches still favored FTS5 for the finite workload. This supports the revised decision within its recorded scope.

The modeled crossover was approximately 28.202 batches. Extreme combinations of the existing build and batch samples gave 17.228–35.471 batches. That is a sensitivity illustration, not a confidence interval or a production threshold.

There was no explicit query warm-up. The five batches do not establish stable cache behavior or explain why later batches were faster. Update timing had one sample; disk persistence, memory pressure and mixed production workloads were outside the study.

## Continuation state

The reviewer preserved both earlier decisions, recorded the scope correction and proposed a separate study with declared warm-up, independent index instances, randomized query order and complete lifecycle measurements. That branch remained **proposed**, because it had not run.

The key finding affects the interpretation of the main conclusion and is marked critical independently of its completed state. The next branch remains unfinished. Execution success, scientific support and branch completion are recorded separately.

This illustrates the intended Skill handoff: another agent reads the persistent experiment, checks the evidence it needs, makes a bounded contribution and leaves an accurate next action. The conversation itself is not part of the experiment's identity.
