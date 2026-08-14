# Failure lab

| Failure | Expected containment | Required evidence |
|---|---|---|
| Identical batch replay | No duplicate state | Same manifest and snapshot digest |
| Conflicting batch replay | Batch quarantined | Conflict reason and unchanged pointer |
| Refund above capture | Financial gate fails | Order/refund totals |
| Negative inventory | Inventory gate fails | SKU and attempted movement |
| Breaking schema | Contract gate fails | Contract version and violation |
| Failure before commit | No rows or frontier advance | Before/after snapshot digest |
| Stale publisher | Conditional update fails | Expected/current pointer version |
| Backfill | New candidate remains inactive | Active pointer before/after |

Local execution proves the semantics. The managed lab repeats the schema, failure, replay,
publication, and backfill cases through S3, Glue, Iceberg, DynamoDB, Athena, and CloudWatch.

