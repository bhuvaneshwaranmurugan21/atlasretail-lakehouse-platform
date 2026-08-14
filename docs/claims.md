# Evidence and claim policy

| Level | Meaning | Current evidence |
|---|---|---|
| `DESIGNED` | Architecture or code exists but has not executed | AWS deployment until a successful lab run |
| `LOCAL_VERIFIED` | Deterministic implementation passed locally and in CI | Failure lab and unit tests |
| `AWS_VERIFIED` | A bounded real AWS run produced immutable evidence | Empty until the workflow succeeds |
| `PRODUCTION_MEASURED` | Sustained production workload and incident history | Not claimed |

Repository documentation must not promote an estimate, simulator result, or architecture diagram
to a higher level. AWS evidence is stored per run under `evidence/aws/<run-id>/` and includes the
source commit SHA so evidence cannot silently drift away from code.
