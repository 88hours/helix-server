"""Tests for core/auth.py"""
import pytest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException


# ---------------------------------------------------------------------------
# auth_enabled
# ---------------------------------------------------------------------------

def test_auth_enabled_true_when_domain_set(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    from core.auth import auth_enabled
    assert auth_enabled() is True


def test_auth_enabled_false_when_domain_not_set(monkeypatch):
    monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
    from core.auth import auth_enabled
    assert auth_enabled() is False


# ---------------------------------------------------------------------------
# _domain / _audience
# ---------------------------------------------------------------------------

def test_domain_returns_env_var(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "my-tenant.auth0.com")
    from core.auth import _domain
    assert _domain() == "my-tenant.auth0.com"


def test_audience_returns_env_var(monkeypatch):
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.myapp.com")
    from core.auth import _audience
    assert _audience() == "https://api.myapp.com"


def test_audience_returns_empty_string_when_not_set(monkeypatch):
    monkeypatch.delenv("AUTH0_AUDIENCE", raising=False)
    from core.auth import _audience
    assert _audience() == ""


# ---------------------------------------------------------------------------
# _fetch_jwks
# ---------------------------------------------------------------------------

def test_fetch_jwks_returns_parsed_json():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"keys": [{"kid": "abc123"}]}
    mock_resp.raise_for_status.return_value = None
    with patch("core.auth.httpx.get", return_value=mock_resp):
        import core.auth
        core.auth._fetch_jwks.cache_clear()
        result = core.auth._fetch_jwks("test.auth0.com")
    assert result["keys"][0]["kid"] == "abc123"
    core.auth._fetch_jwks.cache_clear()


def test_fetch_jwks_raises_503_on_network_failure():
    with patch("core.auth.httpx.get", side_effect=Exception("connection refused")):
        import core.auth
        core.auth._fetch_jwks.cache_clear()
        with pytest.raises(HTTPException) as exc_info:
            core.auth._fetch_jwks("test.auth0.com")
    assert exc_info.value.status_code == 503
    core.auth._fetch_jwks.cache_clear()


# ---------------------------------------------------------------------------
# _rsa_key_for
# ---------------------------------------------------------------------------

def test_rsa_key_for_returns_matching_key():
    from core.auth import _rsa_key_for
    jwks = {"keys": [{"kid": "key1", "kty": "RSA"}, {"kid": "key2", "kty": "RSA"}]}
    assert _rsa_key_for(jwks, "key1")["kid"] == "key1"


def test_rsa_key_for_returns_none_when_no_match():
    from core.auth import _rsa_key_for
    assert _rsa_key_for({"keys": [{"kid": "key1"}]}, "missing") is None


def test_rsa_key_for_returns_none_for_empty_keys():
    from core.auth import _rsa_key_for
    assert _rsa_key_for({"keys": []}, "any") is None


# ---------------------------------------------------------------------------
# _verify — all exception branches
# ---------------------------------------------------------------------------

def test_verify_raises_401_on_malformed_token(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    import jwt
    with patch("core.auth.jwt.get_unverified_header", side_effect=jwt.DecodeError("bad")):
        from core.auth import _verify
        with pytest.raises(HTTPException) as exc_info:
            _verify("not.a.token")
    assert exc_info.value.status_code == 401
    assert "Malformed" in exc_info.value.detail


def test_verify_raises_401_when_signing_key_not_found(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    with patch("core.auth.jwt.get_unverified_header", return_value={"kid": "unknown"}), \
         patch("core.auth._fetch_jwks", return_value={"keys": []}):
        from core.auth import _verify
        with pytest.raises(HTTPException) as exc_info:
            _verify("any.token.value")
    assert exc_info.value.status_code == 401
    assert "key" in exc_info.value.detail.lower()


def test_verify_raises_401_on_expired_signature(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    import jwt
    fake_key = {"kid": "key1"}
    with patch("core.auth.jwt.get_unverified_header", return_value={"kid": "key1"}), \
         patch("core.auth._fetch_jwks", return_value={"keys": [fake_key]}), \
         patch("core.auth._rsa_key_for", return_value=fake_key), \
         patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="pub"), \
         patch("core.auth.jwt.decode", side_effect=jwt.ExpiredSignatureError("expired")):
        from core.auth import _verify
        with pytest.raises(HTTPException) as exc_info:
            _verify("token")
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_verify_raises_401_on_invalid_audience(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    import jwt
    fake_key = {"kid": "key1"}
    with patch("core.auth.jwt.get_unverified_header", return_value={"kid": "key1"}), \
         patch("core.auth._fetch_jwks", return_value={"keys": [fake_key]}), \
         patch("core.auth._rsa_key_for", return_value=fake_key), \
         patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="pub"), \
         patch("core.auth.jwt.decode", side_effect=jwt.InvalidAudienceError("aud")):
        from core.auth import _verify
        with pytest.raises(HTTPException) as exc_info:
            _verify("token")
    assert exc_info.value.status_code == 401
    assert "audience" in exc_info.value.detail.lower()


def test_verify_raises_401_on_invalid_issuer(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    import jwt
    fake_key = {"kid": "key1"}
    with patch("core.auth.jwt.get_unverified_header", return_value={"kid": "key1"}), \
         patch("core.auth._fetch_jwks", return_value={"keys": [fake_key]}), \
         patch("core.auth._rsa_key_for", return_value=fake_key), \
         patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="pub"), \
         patch("core.auth.jwt.decode", side_effect=jwt.InvalidIssuerError("iss")):
        from core.auth import _verify
        with pytest.raises(HTTPException) as exc_info:
            _verify("token")
    assert exc_info.value.status_code == 401
    assert "issuer" in exc_info.value.detail.lower()


def test_verify_raises_401_on_decode_error(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    import jwt
    fake_key = {"kid": "key1"}
    with patch("core.auth.jwt.get_unverified_header", return_value={"kid": "key1"}), \
         patch("core.auth._fetch_jwks", return_value={"keys": [fake_key]}), \
         patch("core.auth._rsa_key_for", return_value=fake_key), \
         patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="pub"), \
         patch("core.auth.jwt.decode", side_effect=jwt.DecodeError("fail")):
        from core.auth import _verify
        with pytest.raises(HTTPException) as exc_info:
            _verify("token")
    assert exc_info.value.status_code == 401


def test_verify_returns_claims_on_success(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    fake_key = {"kid": "key1"}
    claims = {"sub": "github|123", "name": "Alice", "email": "alice@example.com"}
    with patch("core.auth.jwt.get_unverified_header", return_value={"kid": "key1"}), \
         patch("core.auth._fetch_jwks", return_value={"keys": [fake_key]}), \
         patch("core.auth._rsa_key_for", return_value=fake_key), \
         patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="pub"), \
         patch("core.auth.jwt.decode", return_value=claims):
        from core.auth import _verify
        result = _verify("valid.jwt.token")
    assert result["sub"] == "github|123"


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------

def test_get_current_user_returns_demo_user_when_auth_disabled(monkeypatch):
    monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
    from core.auth import get_current_user, _DEMO_USER
    result = get_current_user(request=MagicMock(), credentials=None)
    assert result == _DEMO_USER


def test_get_current_user_validates_bearer_token(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    claims = {"sub": "github|123", "name": "Alice", "email": "alice@example.com"}
    credentials = MagicMock()
    credentials.credentials = "valid-bearer-token"
    with patch("core.auth._verify", return_value=claims):
        from core.auth import get_current_user
        result = get_current_user(request=MagicMock(), credentials=credentials)
    assert result["sub"] == "github|123"


def test_get_current_user_falls_back_to_access_token_query_param(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    claims = {"sub": "github|456"}
    request = MagicMock()
    request.query_params.get.return_value = "query-param-token"
    with patch("core.auth._verify", return_value=claims):
        from core.auth import get_current_user
        result = get_current_user(request=request, credentials=None)
    assert result["sub"] == "github|456"


def test_get_current_user_raises_401_when_no_token_provided(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    request = MagicMock()
    request.query_params.get.return_value = None
    from core.auth import get_current_user
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request=request, credentials=None)
    assert exc_info.value.status_code == 401


def test_verify_includes_audience_when_set(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.myapp.com")
    import jwt as pyjwt
    fake_key = {"kid": "key1"}
    claims = {"sub": "github|123"}
    with patch("core.auth.jwt.get_unverified_header", return_value={"kid": "key1"}), \
         patch("core.auth._fetch_jwks", return_value={"keys": [fake_key]}), \
         patch("core.auth._rsa_key_for", return_value=fake_key), \
         patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="pub"), \
         patch("core.auth.jwt.decode", return_value=claims) as mock_decode:
        from core.auth import _verify
        result = _verify("valid.jwt.token")
    assert result["sub"] == "github|123"
    call_kwargs = mock_decode.call_args[1]
    assert call_kwargs.get("audience") == "https://api.myapp.com"
