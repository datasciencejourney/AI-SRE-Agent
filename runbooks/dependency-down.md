# Dependency down: upstream service unreachable
Symptoms: errors mention upstream service unreachable or connection refused, another service is also logging errors or is silent, no recent deploy on the alerting service.
Likely cause: the dependency crashed, was killed for memory, or is not responding to health checks.
Fix: restart the failing dependency, not the service that raised the alert.
Verify: the alerting service stops reporting upstream errors.
