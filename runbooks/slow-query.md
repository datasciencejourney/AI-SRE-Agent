# Slow query after a release: missing database index
Symptoms: p95 latency climbs, logs show slow query warnings with the same SELECT statement, database connections in use go up, error rate stays moderate.
Likely cause: a new query or migration added a column or filter without an index.
Fix: roll back the release, then add the index and redeploy. Use EXPLAIN on the slow statement to confirm.
Verify: latency returns to normal and slow query warnings stop.
