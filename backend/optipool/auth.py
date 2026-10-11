import cachecontrol
import jwt
import requests
from fastapi import HTTPException, Request
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

CERTS_URL = "https://www.gstatic.com/iap/verify/public_key-jwk"


class Auth:
    def __init__(self, settings):
        self.settings = settings
        self.verifier_request = GoogleRequest(session=cachecontrol.CacheControl(requests.Session()))

    def __call__(self, request: Request):
        if self.settings.auth_mode == "local":
            # Local mode is suitable only for loopback/local Kind with no ingress.
            return "local-demo-user"
        assertion = request.headers.get("x-goog-iap-jwt-assertion")
        if not assertion:
            raise HTTPException(401, "Signed IAP assertion required")
        try:
            if jwt.get_unverified_header(assertion).get("alg") != "ES256":
                raise ValueError("IAP requires ES256")
            claims = id_token.verify_token(
                assertion, self.verifier_request, audience=self.settings.iap_audience, certs_url=CERTS_URL
            )
            if not isinstance(claims.get("aud"), str) or claims["aud"] != self.settings.iap_audience:
                raise ValueError("Invalid audience")
            if "iat" not in claims or "exp" not in claims or claims["exp"] - claims["iat"] > 660:
                raise ValueError("Invalid IAP token lifetime")
            if (
                claims.get("iss") != "https://cloud.google.com/iap"
                or not claims.get("sub")
                or not claims.get("email")
            ):
                raise ValueError("Invalid IAP issuer or identity")
            return claims["email"]
        except Exception:
            raise HTTPException(401, "IAP assertion could not be verified") from None
