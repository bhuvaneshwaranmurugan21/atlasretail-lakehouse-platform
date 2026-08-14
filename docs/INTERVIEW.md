# Interview defense

## Two-minute explanation

AtlasRetail treats a lakehouse load as an immutable generation, not a sequence of mutable folders.
Orders, refunds, and inventory changes pass business and schema invariants, a failed batch changes
nothing, and consumers see data only after a conditional publication pointer moves. Backfills are
isolated generations, so historical repair cannot silently rewrite the current view.

## Questions to expect

1. **How is replay safe?** Batch identity is immutable and conflicting payload reuse is rejected.
2. **How do you prevent partial visibility?** Candidate state is separate; one CAS pointer publishes it.
3. **Why not only partitions?** Partitions optimize access but do not provide correctness or atomicity.
4. **How are refunds and inventory protected?** Refund totals cannot exceed captured value and
   inventory cannot publish negative stock.
5. **How do backfills work?** Build and validate a new generation, then explicitly promote it.
6. **What ran on AWS?** Only a bundle passing `validate_aws_lab_evidence` supports an AWS-lab claim.

