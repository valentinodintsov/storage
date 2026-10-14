import base64
import shutil
import subprocess

import pytest

from app.config import settings
from app.errors import ServiceError
from app.schemas import SignIn
from app.services import signatures
from app.services.signatures import CadesProvider

CONTENT = b'{"number":"1"}'
SIGNATURE = base64.b64encode(b"0\x82fake-cms").decode()


def _cryptcp(monkeypatch, returncode, output):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode, stdout=output.encode(), stderr=b"")

    monkeypatch.setattr(signatures.subprocess, "run", run)
    return calls


def test_valid_signature(monkeypatch):
    calls = _cryptcp(monkeypatch, 0, "Подпись проверена.\n[ErrorCode: 0x00000000]\n")
    provider = CadesProvider()
    assert provider._check(SIGNATURE, CONTENT) is True
    assert provider._check(SIGNATURE, CONTENT) is True
    assert len(calls) == 1  # результат кэшируется
    assert "-errchain" in calls[0] and "-detached" in calls[0]


def test_invalid_signature(monkeypatch):
    _cryptcp(monkeypatch, 249, "DSign.cpp:1141: 0x80090006\nОшибка: Подпись не верна.\n[ErrorCode: 0x200001f9]\n")
    assert CadesProvider()._check(SIGNATURE, CONTENT) is False


def test_revocation_offline_is_not_cached(monkeypatch):
    calls = _cryptcp(monkeypatch, 249, "0x80092013\n[ErrorCode: 0x200001f9]\n")
    provider = CadesProvider()
    assert provider._check(SIGNATURE, CONTENT) is None
    assert provider._check(SIGNATURE, CONTENT) is None
    assert len(calls) == 2


def test_revocation_check_can_be_disabled(monkeypatch):
    calls = _cryptcp(monkeypatch, 0, "[ErrorCode: 0x00000000]\n")
    monkeypatch.setattr(settings, "cades_check_revocation", False)
    CadesProvider()._check(SIGNATURE, CONTENT)
    assert "-norev" in calls[0]


def test_cryptcp_missing(monkeypatch):
    monkeypatch.setattr(settings, "cryptcp_path", "/nonexistent/cryptcp")
    assert CadesProvider()._check(SIGNATURE, CONTENT) is None


def test_sign_rejects_invalid_signature(monkeypatch):
    _cryptcp(monkeypatch, 249, "0x80090006\n[ErrorCode: 0x200001f9]\n")
    with pytest.raises(ServiceError):
        CadesProvider().sign(None, None, CONTENT, None, SignIn(signature=SIGNATURE))


@pytest.mark.skipif(not shutil.which(settings.cryptcp_path), reason="КриптоПро CSP не установлен")
def test_real_cryptcp_rejects_garbage():
    assert CadesProvider()._check(SIGNATURE, CONTENT) is False
