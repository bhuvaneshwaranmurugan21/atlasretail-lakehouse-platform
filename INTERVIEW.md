# AtlasRetail interview defense

## Two-minute explanation

AtlasRetail addresses a subtle lakehouse problem: six Iceberg tables can each commit atomically and
still expose an inconsistent retail business state. I designed immutable batch manifests, isolated
generation builds, retail reconciliation gates, and a conditional active-generation pointer. This
makes retries idempotent, prevents a failed or stale publisher from becoming visible, and keeps
backfills separate until approval. The local oracle tests the semantics cheaply; the bounded AWS lab
uses Glue 5, Iceberg, Step Functions, DynamoDB, Athena, S3, KMS, and CloudWatch and records evidence
before destroying the infrastructure.

## Questions I expect

1. **Why not rely only on Iceberg snapshots?** They are atomic per table; the business generation
   spans multiple tables.
2. **How is exactly-once achieved?** It is not a transport promise. The manifest digest plus a
   conditional batch record gives exactly-once business effect under at-least-once delivery.
3. **What happens when the same ID has different bytes?** It is a hard conflict and quarantined.
4. **How are late dimensions handled?** Product versions resolve by event time and knowledge time;
   an unknowable version fails the gate rather than silently joining to the latest row.
5. **Can a backfill overwrite current data?** It builds a new isolated generation and has no serving
   effect until a compare-and-swap publication.
6. **What if two publishers race?** Only the expected pointer version can advance; the stale writer
   fails and its generation remains inspectable.
7. **How do you reconcile finance?** Line totals, order equation, captured payments, refunds, and
   return quantities are checked before publication.
8. **How do you protect inventory correctness?** Movements are ordered by event time and cumulative
   stock cannot become negative for a product/store pair.
9. **What did you really measure?** Local evidence is labeled `LOCAL_VERIFIED`; AWS runtime, scan,
   service, failure, recovery, and teardown evidence become `AWS_VERIFIED` only after the real run.
10. **What is not production complete?** Multi-region DR, streaming ingestion, PII controls, large
    concurrency, and months of operational history are intentionally not claimed.
