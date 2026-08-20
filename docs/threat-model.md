# Threat model

| Threat | Control | Residual risk |
|---|---|---|
| Untrusted fork obtains AWS access | GitHub OIDC `sub` is restricted to owner, repository, and `main` | Compromised maintainer or trusted workflow |
| Public object exposure | S3 public-access block, ownership enforcement, and TLS-only policy | AWS account administrator override |
| Batch ID is reused with other content | Canonical digest, exact manifest location, and conditional registration | Compromised producer can submit a new batch identity |
| Concurrent environments consume shared account capacity | DynamoDB account lease and GitHub concurrency group | Manual console resources bypass the lease |
| Static credentials leak | GitHub receives short-lived OIDC credentials; no AWS keys are stored | Logs may contain non-secret operational identifiers |
| Partial generation becomes active | Generation-scoped writes and conditional publication | A reader that bypasses the serving boundary can query physical data |
| Stale publisher replaces newer state | Registration-owned generation and DynamoDB pointer-version condition | Control-plane administrator can bypass the workflow |
| Deployment timeout skips cleanup | Independent teardown job and persisted run authority | GitHub-wide outage requires incident-specific rescue |
| Teardown silently leaves resources | Named service checks, recursive state inspection, and run-tag inventory | Unsupported or untagged resource types require manual inspection |
| Retained data grows without bound | S3 lifecycle, log retention, and explicit generation cleanup design | Failed cleanup requires operator intervention |

Synthetic fixtures contain no personal data or payment-card numbers. KMS encryption validates key
policy and audit behaviour; it does not establish PCI DSS compliance.
