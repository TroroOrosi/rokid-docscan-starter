"""Guard the actual product's test/build coverage, without an Android runtime."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_android_ci_includes_pure_java_tests_via_repository_wrapper():
    workflow = (ROOT / '.github/workflows/android-relay.yml').read_text(encoding='utf-8')
    assert 'sh android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug' in workflow


def test_android_ci_avoids_obsolete_sdk_tools_package():
    workflow = (ROOT / '.github/workflows/android-relay.yml').read_text(encoding='utf-8')
    assert 'packages: platform-tools' in workflow


def test_android_ci_preserves_the_glassdoc_apk_and_identity_report():
    workflow = (ROOT / '.github/workflows/android-relay.yml').read_text(encoding='utf-8')
    assert 'android-relay/glassdoc/build/outputs/apk/debug/glassdoc-debug.apk' in workflow
    assert re.search(r'apksigner"?\s+verify', workflow)
    assert re.search(r'aapt2"?\s+dump badging', workflow)
    assert 'sha256sum' in workflow


def test_phone_profile_retains_recorded_fastapi_stack_without_native_extras():
    profile = ROOT / 'requirements-phone.txt'
    constraints = ROOT / 'constraints-phone.txt'
    assert profile.is_file() and constraints.is_file()
    text = profile.read_text(encoding='utf-8')
    pinned = constraints.read_text(encoding='utf-8')
    assert '-c constraints-phone.txt' in text
    assert 'uvicorn[standard]' not in text
    for requirement in ('fastapi==0.99.1', 'pydantic==1.10.26', 'starlette==0.27.0'):
        assert requirement in pinned


def test_ci_exercises_windows_locking_and_phone_compatibility():
    workflow = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
    assert 'windows-latest' in workflow
    assert 'tests/test_browser_guard.py' in workflow
    assert 'constraints-phone.txt' in workflow
