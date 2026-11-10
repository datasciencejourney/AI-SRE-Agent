# False alarm: short blip that recovered
Symptoms: a brief error burst lasting one or two minutes, a transient network reset, error rate already back to normal when investigated.
Likely cause: a network hiccup or a single failed request batch.
Fix: no action. Consider a longer evaluation window on the alert rule so it does not fire on blips.
Verify: error rate is normal and stays normal.
