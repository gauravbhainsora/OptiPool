# Use IAP for organisation-only browser access

The dashboard serves a shared internal audience, while cloud collection uses a service account. Use organisation Google sign-in through IAP at the GKE ingress, granting admitted users the same dashboard capabilities and validating the signed IAP identity in the backend. This relies on Google identity and ingress configuration, but avoids making each dashboard viewer provide local gcloud credentials; local CLI access and runtime collection identities remain separate.

Reference: [GKE IAP setup](https://docs.cloud.google.com/iap/docs/enabling-kubernetes-howto) and [signed identity validation](https://docs.cloud.google.com/iap/docs/signed-headers-howto).
