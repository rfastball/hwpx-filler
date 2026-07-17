"""부팅 프로필 준비 가드 — ``hwpxfiller.webapp.app._prepare_webview_profile`` (#74 리뷰3).

단일 인스턴스 가드(뮤텍스)가 이 홈에 우리뿐임을 보장하므로, 부팅은 webview_root 를 통째
청소하고 고정 ``profile`` 폴더를 새로 만든다 — 이전의 per-pid 폴더 + 부팅 스윕 + profile.lock
기계를 대체한다. 이 가드는 (1) 크래시 고아·구판 EBWebView 잔재·재시작 간 공유 디스크 캐시가
말끔히 사라지고(#69/#71 스테일 자산 이중 차단), (2) 새 프로필 폴더가 실제로 생기는지를 본다.
"""
from __future__ import annotations

from hwpxfiller.webapp.app import _prepare_webview_profile


def test_prepare_purges_orphans_and_legacy_layout(tmp_path):
    root = tmp_path / "webview"
    orphan = root / "profile"           # 이전 부팅의 크래시 고아(같은 고정 이름)
    (orphan / "Default" / "Cache").mkdir(parents=True)
    (orphan / "Default" / "Cache" / "stale.js").write_text("구자산", encoding="utf-8")
    legacy = root / "EBWebView"         # 구판 단일 폴더 레이아웃 잔재
    (legacy / "Default").mkdir(parents=True)
    (root / "profile-99999").mkdir()    # 구판 per-pid 잔재

    storage = _prepare_webview_profile(root)

    assert storage == root / "profile"
    assert storage.is_dir()             # 새 프로필 폴더 실재
    assert not list(storage.iterdir())  # 비어 있음 — 고아 자산 소거(스테일 캐시 서빙 불가)
    assert not legacy.exists()          # 구판 레이아웃 잔재 제거
    assert not (root / "profile-99999").exists()


def test_prepare_first_boot_creates_root(tmp_path):
    # 첫 부팅 — webview_root 자체가 없어도 예외 없이 프로필을 만든다.
    storage = _prepare_webview_profile(tmp_path / "webview")
    assert storage.is_dir()
