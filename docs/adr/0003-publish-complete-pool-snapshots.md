# Publish complete pool snapshots and retain old data on refresh failure

Capacity estimates correlate a pool's configuration, nodes, and workloads. A user-requested refresh publishes a new saved snapshot only after collection of these components succeeds completely; a failed refresh leaves the previous complete snapshot available and displays an error. This prioritises coherent saved observations over partially fresher data, although collection spans a time interval and does not constitute an atomic snapshot of live Kubernetes state.
