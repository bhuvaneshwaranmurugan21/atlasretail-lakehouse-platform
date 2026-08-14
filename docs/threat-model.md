# Threat model

| Threat | Design control | Remaining managed proof |
|---|---|---|
| Public raw or curated data | S3 public-access block and encryption | Config/policy evidence |
| Cross-run data overwrite | Immutable run prefixes and generation IDs | Object-version proof |
| Corrupt replay | Batch identity and payload digest conflict | Managed replay trace |
| Partial publication | Conditional active pointer | DynamoDB conditional-failure trace |
| Destructive schema drift | Contract gate and quarantine | Real schema injection |
| Evidence disclosure | Synthetic data and redacted identifiers | Bundle review |

This is a technical threat model, not a compliance certification.

