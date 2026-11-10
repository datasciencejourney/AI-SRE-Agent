# Traffic spike: sudden overload, nothing is broken
Symptoms: request rate several times higher than normal, cpu near maximum, logs show queue full or load shedding or worker pool saturated, latency high, no deploy close to the start.
Likely cause: a marketing campaign, a retry storm, or a bot. The code is fine.
Fix: do not roll back. Scale out, enable rate limiting, or wait for the spike to pass.
Verify: latency and errors fall as traffic or capacity changes.
