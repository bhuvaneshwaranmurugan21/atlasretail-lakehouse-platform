# Workload and capacity model

The AWS lab uses bounded synthetic orders, returns, and inventory movements. It records input
rows/bytes, file-size distribution, partition count, Glue runtime, Athena bytes scanned, snapshot
publication latency, replay time, and cost. These are lab measurements, not production claims.

Production sizing separates ingestion throughput from query efficiency. Small files, skewed
business dates, and excessive partition cardinality can dominate cost even when total volume is
moderate. Compaction and partition evolution are therefore explicit operational decisions.

