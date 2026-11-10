# Config change broke the service: connection pool exhausted
Symptoms: error rate jumps right after a release, logs show database connection pool timeout or QueuePool limit reached, db connections in use are very low or maxed out, p95 latency spikes.
Likely cause: a deploy changed a setting such as DB_POOL_SIZE or a timeout in a config file.
Fix: roll the service back to the previous version, then correct the config value and redeploy.
Verify: error rate returns below 5 percent within two minutes of the rollback.
