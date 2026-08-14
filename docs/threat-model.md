# Threat model

| Threat | Control | Residual risk |
|---|---|---|
| Untrusted fork obtains AWS access | GitHub OIDC `sub` is restricted to owner/repo/main | Compromised maintainer/main workflow |
| Public object exposure | S3 public access block, ownership enforcement, TLS-only policy | AWS account administrator override |
| Data tampering or ID reuse | Manifest SHA-256 proofs and conditional batch registration | Compromised producer can create a new valid ID |
| Concurrent portfolio labs overspend | DynamoDB lease and GitHub concurrency group | Manual console resources bypass lock |
| Secret leakage | No static AWS keys; short-lived OIDC credentials | Logs may contain non-secret business data |
| Failed run becomes visible | Generation isolation and conditional publication | Bugs shared by validator and transformer |
| Deployment job timeout skips cleanup | Independent teardown job plus immutable run authority | GitHub-wide outage still requires rescue workflow |
| Unbounded retention | S3 lifecycle, log retention, saved destroy plan, rescue workflow | Failed teardown needs manual intervention |

Synthetic data contains no personal or payment-card information. KMS encryption is used to prove
key policy and audit behaviour, not to claim PCI DSS compliance.
