# Terraform topology

This module creates only bounded, tagged lab primitives. The Glue job definition and script
upload are intentionally performed by the managed-execution workflow after local verification.
No NAT gateway, persistent cluster, Redshift resource, or scheduled compute is created.

