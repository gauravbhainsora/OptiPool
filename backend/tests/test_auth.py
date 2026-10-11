import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from google.oauth2 import id_token
from optipool.app import create_app


@pytest.mark.parametrize(
    "change", [{}, {"aud": "wrong"}, {"iss": "wrong"}, {"exp": 1}, {"iat": time.time() + 1000}, {"iat": None}]
)
def test_signed_iap_assertions(settings, monkeypatch, change):
    settings.auth_mode = "iap"
    settings.iap_audience = "/projects/123/global/backendServices/456"
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test", alg="ES256", use="sig")
    monkeypatch.setattr(id_token, "_fetch_certs", lambda *args: {"keys": [jwk]})
    claims = {
        "iss": "https://cloud.google.com/iap",
        "aud": settings.iap_audience,
        "sub": "123",
        "email": "user@example.org",
        "iat": int(time.time()) - 5,
        "exp": int(time.time()) + 300,
        **change,
    }
    if change.get("iat", "present") is None:
        claims.pop("iat")
    signed = jwt.encode(claims, key, algorithm="ES256", headers={"kid": "test"})
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").status_code == 200
        assert (
            client.get(
                "/api/inventory", headers={"x-goog-authenticated-user-email": "accounts.google.com:fake"}
            ).status_code
            == 401
        )
        status = client.get("/api/inventory", headers={"x-goog-iap-jwt-assertion": signed}).status_code
        assert status == (401 if change else 200)
