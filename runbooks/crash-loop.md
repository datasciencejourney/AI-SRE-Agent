# Crash loop: container exits on startup
Symptoms: no requests served, error rate 100 percent, logs show KeyError for a missing environment variable, container exited with code 1 and keeps restarting.
Likely cause: a release renamed or removed an environment variable that is not set in the deployment.
Fix: roll back to the previous version, then set the new variable everywhere before redeploying.
Verify: the service stays up and starts serving requests.
