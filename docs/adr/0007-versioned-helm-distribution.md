# Prepare versioned Helm deployment before the first code push

OptiPool is intended for open-source distribution, with reproducible local testing and deployment documentation. Prepare a versioned Helm chart alongside the application before the first code push, including configuration examples, persistent SQLite storage, installation/upgrade instructions, and package installation tests. Chart and application versions remain distinct, and the single database-owning instance requirement is preserved rather than exposing unsupported backend scaling.

The release gate is defined in [release-readiness.md](../release-readiness.md). Chart packaging and local checks are preparatory work; publishing the source, images, or chart is a separate release action.
