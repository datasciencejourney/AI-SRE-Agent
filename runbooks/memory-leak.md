# Memory leak: service memory keeps growing
Symptoms: memory climbs steadily for many minutes, garbage collection overhead warnings, latency slowly rises, no sudden spike in traffic.
Likely cause: an unbounded in-memory cache or a collection that is never emptied, usually from a recent release.
Fix: restart the service to clear memory now, then fix the cache with an eviction policy or size limit.
Verify: memory drops to its normal level after the restart.
