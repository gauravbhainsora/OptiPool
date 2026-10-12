import pytest
from optipool.config import Settings
from optipool.demo import DemoCollector


@pytest.fixture
def settings(tmp_path):
    return Settings(database=str(tmp_path / "test.db"))


@pytest.fixture
def saved(settings):
    demo = DemoCollector(settings)
    pool = demo.discover()[0][0]
    return {"id": "saved-snapshot", "saved_at": 1728000000, **demo.collect(pool)}


@pytest.fixture
def iap_headers(settings, monkeypatch):
    """A signed synthetic IAP assertion; only the external certificate fetch is stubbed."""
    import json
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec
    from google.oauth2 import id_token

    settings.auth_mode = "iap"
    settings.iap_audience = "/projects/123/global/backendServices/456"
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="review-test", alg="ES256", use="sig")
    monkeypatch.setattr(id_token, "_fetch_certs", lambda *args: {"keys": [jwk]})
    token = jwt.encode(
        dict(
            iss="https://cloud.google.com/iap",
            aud=settings.iap_audience,
            sub="123",
            email="test@example.org",
            iat=int(time.time()) - 5,
            exp=int(time.time()) + 300,
        ),
        key,
        algorithm="ES256",
        headers={"kid": "review-test"},
    )
    return {"x-goog-iap-jwt-assertion": token}
