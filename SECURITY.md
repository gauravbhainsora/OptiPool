# Security policy

This initial 0.1 series is under development. Production rollout requires the documented nonproduction validation and organization access configuration.

Report suspected vulnerabilities privately to the repository owner through GitHub's private vulnerability reporting feature when enabled. Otherwise contact the maintainer through their GitHub profile to arrange a private channel. Do not publish credentials, collected observations or exploitable details in a public issue. No guaranteed response time is currently offered.

Production uses signed IAP assertions and an approved organization/group policy. Unsigned identity headers are not trusted. Health endpoints contain no cloud data. Collection uses one shared read-only runtime identity, with separate Google IAM, Kubernetes authorization and network requirements. Admission and scheduling uncertainty is exposed in estimation results.

Local/demo auth is for loopback or isolated private testing only. Do not expose it publicly. SQLite, backups, exports and audit records can contain sensitive infrastructure and user identity data; operators must apply their organization's storage/access/retention controls. No credentials or service-account key material belongs in Git or Helm values.

Spreadsheet exports escape leading formula characters from untrusted names/labels. Keep dependencies current and validate lock updates. The app does not perform deployment, scaling, preemption or billing/commitment mutations.
