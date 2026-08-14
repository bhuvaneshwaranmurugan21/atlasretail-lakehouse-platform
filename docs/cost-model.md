# Cost controls

- Small synthetic input and one bounded Glue/Athena experiment.
- No NAT gateway or always-on cluster.
- Athena queries are scoped to known partitions and record bytes scanned.
- DynamoDB control tables use on-demand capacity.
- CloudWatch retention and S3 lab data are short-lived.
- Run/expiry tags and verified Terraform destroy are mandatory.

Calculator estimates are captured before deployment; actual cost is recorded only after measured
usage exists.

