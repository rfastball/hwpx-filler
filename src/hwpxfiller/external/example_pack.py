"""동봉 예제 세트의 설치 몸통 — 자산 해석·복사·그룹 지정·데이터 고정·설치 manifest.

설계 정본은 ``docs/ONBOARDING_TUTORIAL.md`` §1 D1·§4.1~4.2·§4.5(슬라이스 B, #891).
D1 이 정한 주입 방식은 **빈 상태 제안 + 명시 버튼**이다: 최초 부팅 자동 설치는 사용자 홈
무단 쓰기라, **이 모듈은 :func:`install` 이 불리기 전에는 홈에 아무것도 쓰지 않는다**
(import 부작용 0 · :func:`asset_root` 와 :func:`entry_point_state` 는 읽기 전용).

**자산 해석은 두 갈래 하나**(§4.2): source 실행은 저장소 ``examples/onboarding/``, frozen
제품은 ``sys._MEIPASS`` 아래 동봉 사본이다 — :func:`hwpxfiller.webapp.app.web_artifact` 와
같은 ``sys.frozen``/``sys._MEIPASS`` 분기이고 범용 ``resource_path()`` 헬퍼는 이 저장소에
없다(만들지 않는다 — 전례가 하나면 관용구도 하나다).

**몸통은 여기, 조립은 호출측**: 파일 복사(잠금·매체 라우팅·충돌 접미)는
:class:`~hwpxfiller.external.template_files.TemplateFileStore`, 그룹 지정은
``TemplateGroupModel.set_group``, 데이터 고정은
:class:`~hwpxfiller.external.dataset_store.DatasetPoolRegistry` 를 **그대로 받아** 쓴다
(인라인 재구현 금지, §4.2). 협력자를 인자로 받는 이유는 계층이기도 하다 — 그룹 모델은
링2(``webapp/template_groups.py``)에 살고 external 은 그 위를 import 할 수 없으므로,
식별키 계산(``rel_key``)도 ``group_key`` 로 주입받는다.

**설치 manifest**(§1 D4)는 설정 중첩 키 ``tutorial.manifest`` 에 앉는다 — 제거(슬라이스 C)의
입력이다. 그룹은 실체가 아니라 소속이라 「그룹 삭제 한 번으로 통째 제거」가 성립하지 않고,
제거는 **manifest 기재 항목만** 걷어야 사용자가 직접 넣은 이웃 파일을 건드리지 않는다.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from hwpxfiller.domain.dataset_reference import DatasetReference

from . import settings

__all__ = (
    "EXAMPLE_GROUP",
    "HWPX_ASSETS",
    "TXT_ASSETS",
    "DATA_ASSETS",
    "asset_root",
    "entry_point_state",
    "confirm_text",
    "install",
    "removal_plan",
    "remove_confirm_text",
    "remove",
)

#: 설치된 템플릿이 들어갈 그룹 이름(hwpx·txt 두 매체에 같은 이름). 소속이 곧 존재라
#: 빈 그룹은 만들어지지 않는다 — 제거는 manifest 가 진다(§1 D4).
EXAMPLE_GROUP = "예제"

#: 동봉 자산 파일 이름 — 정본은 ``examples/onboarding/make_assets.py`` 의 생성 목록이고
#: 여기 이름들이 그 산출물과 어긋나면 :func:`install` 이 시끄럽게 멈춘다(조용한 부분 설치 금지).
HWPX_ASSETS = ("계약체결안내.hwpx", "구매추진안내.hwpx", "공고서_연습.hwpx")
TXT_ASSETS = ("계약안내_기안.txt", "오류연습_보증금.txt")
DATA_ASSETS = ("계약목록.csv", "계약목록_2.csv")

# ------------------------------------------------------------------ 자산 원천
def asset_root() -> Path:
    """동봉 예제 자산 폴더 — frozen 은 ``sys._MEIPASS``, source 는 저장소 ``examples/onboarding``.

    ``web_artifact()`` 와 **같은 분기**다(§4.2). source 경로는 이 파일 기준 상대로 푼다:
    ``<repo>/src/hwpxfiller/external/example_pack.py`` → ``parents[3]`` = ``<repo>``.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "examples" / "onboarding"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[3] / "examples" / "onboarding"


def _asset_paths() -> "list[tuple[str, Path]]":
    """``(kind, 경로)`` 전수 — 부재 자산은 **설치 시작 전에** loud 로 잡는다.

    부분 설치는 「무엇이 설치됐는지」를 아무도 모르는 상태를 남긴다. 자산이 하나라도 없으면
    (동봉 누락·손상 배포본) 홈을 건드리기 전에 멈춘다.
    """
    root = asset_root()
    plan: "list[tuple[str, Path]]" = []
    for name in HWPX_ASSETS:
        plan.append(("hwpx", root / "templates" / name))
    for name in TXT_ASSETS:
        plan.append(("txt", root / "text_templates" / name))
    for name in DATA_ASSETS:
        plan.append(("data", root / "data" / name))
    missing = [str(p) for _kind, p in plan if not p.is_file()]
    if missing:
        raise FileNotFoundError(
            "동봉 예제 자산을 찾지 못했습니다: " + ", ".join(missing)
        )
    return plan


# ------------------------------------------------------------------ 진입점 판정·문안
def entry_point_state() -> dict:
    """상시 진입점·빈 상태 버튼의 **라벨과 사실**(링2 가 발명하지 않게 Python 이 낸다).

    설치돼 있어도 버튼은 살아 있다 — 되돌리기가 재설치이기 때문이다(§1 D4). 라벨만 갈린다.
    """
    installed = settings.load_tutorial_manifest() is not None
    count = len(HWPX_ASSETS) + len(TXT_ASSETS) + len(DATA_ASSETS)
    return {
        "installed": installed,
        "label": "예제 다시 설치…" if installed else "예제로 시작하기…",
        "hint": (
            f"동봉 예제 {count}건을 처음 상태로 되돌립니다."
            if installed
            else f"동봉 예제 {count}건을 라이브러리에 넣고 데이터를 고정합니다."
        ),
        # 제거 어포던스(#892)는 **설치돼 있을 때만** 선다 — 걷을 것이 없는 자리에 파괴
        # 동사를 세우면 누를 때야 「설치된 예제가 없습니다」를 만난다. 라벨·힌트가 여기
        # 함께 앉는 이유는 설치 라벨과 같다: 링2 가 「이미 설치됨」을 다시 판정하면 같은
        # 사실을 두 곳이 말한다.
        "removable": installed,
        "remove_label": "예제 걷어내기…",
        "remove_hint": "설치한 예제만 걷습니다. 되돌리려면 다시 설치하세요.",
    }


def confirm_text(*, hwpx_root: Path, txt_root: Path, data_dir: Path) -> str:
    """설치 확인 재진술 — **무엇을 몇 건, 어디에** 쓰는지. 판정·수치는 Python, 확인 UI 는 웹.

    재설치면 덮어쓴다는 사실을 같은 문안에서 말한다(조용한 덮어쓰기 금지).
    """
    lines = [
        f"동봉 예제를 설치합니다. 지금 홈에 다음 {len(HWPX_ASSETS) + len(TXT_ASSETS) + len(DATA_ASSETS)}건을 씁니다.",
        "",
        f"· HWPX 서식 {len(HWPX_ASSETS)}건 → {hwpx_root}",
        f"· TXT 기안 {len(TXT_ASSETS)}건 → {txt_root}",
        f"· 예제 데이터 {len(DATA_ASSETS)}건 → {data_dir} (데이터 풀에 고정)",
        "",
        f"템플릿 {len(HWPX_ASSETS) + len(TXT_ASSETS)}건은 '{EXAMPLE_GROUP}' 그룹으로 묶입니다.",
    ]
    if settings.load_tutorial_manifest() is not None:
        lines.append("이미 설치돼 있어 지난 설치분을 덮어쓰고 처음 상태로 되돌립니다.")
    return "\n".join(lines)


# ------------------------------------------------------------------ 설치
def _copy_template(
    *,
    file_store,
    source: Path,
    root: Path,
    prior_paths: "set[str]",
) -> Path:
    """자산 1건을 라이브러리로 — 지난 설치분만 자리를 비우고 남의 동명 파일은 건드리지 않는다.

    :meth:`TemplateFileStore.copy_into_library` 는 이름 충돌을 ``이름 (2).ext`` 로 피한다.
    재설치가 그 규칙에 그대로 걸리면 사본이 늘어 「같은 상태 복원」이 성립하지 않으므로,
    **지난 manifest 에 기재된 그 경로**일 때만 먼저 비운다. 기재에 없는 동명 파일은 사용자가
    직접 넣은 남의 파일이라 접미로 비켜 가고, 그 사실은 호출측 결과 문구가 재진술한다.
    """
    dest = root / source.name
    if dest.exists() and str(dest) in prior_paths:
        dest.unlink()
    return file_store.copy_into_library(source)


def install(
    *,
    file_store,
    hwpx_groups,
    txt_groups,
    hwpx_root: "str | Path",
    txt_root: "str | Path",
    pool_registry,
    group_key,
    data_dir: "str | Path",
) -> dict:
    """예제 세트를 홈에 설치하고 manifest 를 남긴다 — 결과 요약 dict 를 돌려준다.

    협력자는 전부 주입이다(위 모듈 주석): ``file_store`` 는
    :class:`~hwpxfiller.external.template_files.TemplateFileStore`, ``hwpx_groups``/
    ``txt_groups`` 는 ``set_group(key, group)`` 를 가진 그룹 모델, ``pool_registry`` 는
    :class:`~hwpxfiller.external.dataset_store.DatasetPoolRegistry`, ``group_key`` 는
    ``(경로, 루트) -> 식별키`` 계산(링2 ``template_groups.rel_key``)이다.

    **재설치는 복원이다**: 지난 manifest 기재분을 덮어쓰고 manifest 를 새로 쓴다. 데이터 풀은
    같은 정체성(경로+시트)이면 새 슬롯을 만들지 않고 기존 슬롯을 되살린다 — 수명은 보존하되
    보관 상태였으면 실행 후보로 되돌린다(사용자가 방금 「다시 설치」를 확정했다).

    반환: ``{"templates": [...], "data_files": [...], "pool_keys": [...], "renamed": [...]}``.
    ``renamed`` 는 남의 동명 파일 때문에 접미가 붙은 건 — 조용히 넘기지 말라고 싣는다.
    """
    plan = _asset_paths()  # 자산 부재는 홈을 건드리기 전에 loud
    hwpx_root = Path(hwpx_root)
    txt_root = Path(txt_root)
    data_dir = Path(data_dir)

    prior = settings.load_tutorial_manifest() or {}
    prior_paths = {
        str(t.get("path", "")) for t in prior.get("templates", []) if isinstance(t, dict)
    }
    prior_paths |= {str(p) for p in prior.get("data_files", []) if isinstance(p, str)}

    templates: "list[dict]" = []
    renamed: "list[str]" = []
    data_files: "list[str]" = []
    pool_keys: "list[str]" = []

    for kind, source in plan:
        if kind == "data":
            data_dir.mkdir(parents=True, exist_ok=True)
            dest = data_dir / source.name
            shutil.copy2(source, dest)
            data_files.append(str(dest))
            pool_keys.append(_pin_dataset(pool_registry, dest))
            continue
        root = hwpx_root if kind == "hwpx" else txt_root
        model = hwpx_groups if kind == "hwpx" else txt_groups
        dest = _copy_template(
            file_store=file_store, source=source, root=root, prior_paths=prior_paths
        )
        if dest.name != source.name:
            renamed.append(f"'{source.name}' → '{dest.name}'")
        key = group_key(dest, root)
        model.set_group(key, EXAMPLE_GROUP)
        templates.append({"media": kind, "path": str(dest), "key": key})

    settings.save_tutorial_manifest(
        group=EXAMPLE_GROUP,
        templates=templates,
        data_files=data_files,
        pool_keys=pool_keys,
    )
    return {
        "templates": templates,
        "data_files": data_files,
        "pool_keys": pool_keys,
        "renamed": renamed,
    }


# ------------------------------------------------------------------ 제거(#892 · §1 D4)
# 「그룹 삭제 한 번으로 통째 제거」는 성립하지 않는다(그룹은 실체가 아니라 소속이다). 제거는
# **manifest 기재 항목만** 걷는다: 템플릿은 매체 store 의 ``.trash`` 로 건별 이동(기존 기제
# 재사용), 데이터는 고정 해제 + 파일 제거, 그룹 해산, manifest 소거. **벌크 undo 는 만들지
# 않는다** — 자산이 번들에 있으므로 되돌리기는 재설치가 대신하고, 그 사실을 확인 문안이 말한다.
def _require_inside(root: Path, path: Path, what: str) -> Path:
    """manifest 경로가 그 매체의 제자리 안인지 — 벗어나면 loud 거절(경로 탈출 전례).

    manifest 는 설정 파일이라 손편집·구버전·이관으로 라이브러리 밖을 가리킬 수 있다. 그 값을
    그대로 ``trash``/``unlink`` 에 먹이면 제거가 **임의 파일 삭제 권한**이 된다
    (:meth:`~hwpxfiller.external.dataset_store.DatasetPoolRegistry.slot_path` 와 같은 규율).
    루트 자신도 거절한다 — 라이브러리 폴더째 옮기는 경로는 이 동사의 것이 아니다.
    """
    try:
        resolved = path.resolve()
        base = root.resolve()
    except OSError as exc:  # 접근 불가 경로도 조용히 통과시키지 않는다
        raise ValueError(f"{what} 경로를 확인할 수 없습니다: {path}") from exc
    if resolved == base or not resolved.is_relative_to(base):
        raise ValueError(f"설치 기재의 {what} 경로가 제자리를 벗어났습니다: {path}")
    return path


def removal_plan(
    *, hwpx_root: "str | Path", txt_root: "str | Path", data_dir: "str | Path"
) -> "dict | None":
    """제거 대상 전수 — 미설치면 ``None``, 기재가 제자리를 벗어났으면 ``ValueError``.

    **읽기 전용**이다: 확인 왕복의 1차(재진술)와 2차(실행)가 같은 목록을 보게 하는 단일
    몸통이라, 여기서 홈을 건드리지 않는다. 반환은
    ``{"group", "templates": [{"media", "path", "key"}], "data_files": [Path], "pool_keys": [str]}``
    이고 ``path`` 는 :class:`~pathlib.Path` 다(호출측이 다시 성형하지 않게).

    실재 여부는 **묻지 않는다** — 사용자가 이미 지웠거나 제자리에서 고쳤어도 기재는 기재이고,
    「무엇을 걷는가」의 판정은 manifest 하나가 진다(#892 완료 기준). 대신 사라진 건은
    :func:`remove` 가 결과에 실어 재진술한다.
    """
    manifest = settings.load_tutorial_manifest()
    if manifest is None:
        return None
    roots = {"hwpx": Path(hwpx_root), "txt": Path(txt_root)}
    templates: "list[dict]" = []
    for entry in manifest.get("templates", []):
        media = entry.get("media")
        root = roots.get(media)
        if root is None:
            raise ValueError(f"설치 기재의 템플릿 매체를 알 수 없습니다: {media!r}")
        path = _require_inside(root, Path(entry["path"]), "템플릿")
        templates.append({"media": media, "path": path, "key": str(entry.get("key", ""))})
    raw_data = manifest.get("data_files", [])
    if not isinstance(raw_data, list) or any(not isinstance(p, str) for p in raw_data):
        raise ValueError("설치 기재의 데이터 파일 목록이 올바르지 않습니다.")
    data_files = [
        _require_inside(Path(data_dir), Path(p), "예제 데이터") for p in raw_data
    ]
    raw_keys = manifest.get("pool_keys", [])
    if not isinstance(raw_keys, list) or any(not isinstance(k, str) for k in raw_keys):
        raise ValueError("설치 기재의 풀 등록 키 목록이 올바르지 않습니다.")
    group = manifest.get("group")
    if not isinstance(group, str) or not group.strip():
        raise ValueError("설치 기재의 그룹 이름이 비어 있습니다.")
    return {
        "group": group.strip(),
        "templates": templates,
        "data_files": data_files,
        "pool_keys": list(raw_keys),
    }


def remove_confirm_text(plan: dict) -> str:
    """제거 확인 재진술 — **무엇이 몇 건** 사라지는지와 되돌리는 법. 문안·수치는 Python.

    벌크 undo 슬롯이 없다는 사실(§1 D4)을 숨기지 않고 같은 문안에서 말한다: 되돌리기는
    재설치다. 「기재분만 걷는다」도 함께 말한다 — 예제를 고쳐 다른 이름으로 저장해 둔
    사용자가 그것까지 사라진다고 읽지 않게.
    """
    templates = plan["templates"]
    return "\n".join([
        f"설치한 예제 {len(templates) + len(plan['data_files'])}건을 걷습니다.",
        "",
        f"· 템플릿 {len(templates)}건 — 라이브러리에서 걷습니다",
        f"· 예제 데이터 {len(plan['data_files'])}건 — 파일을 지웁니다",
        f"· 데이터 풀 고정 {len(plan['pool_keys'])}건 — 해제합니다",
        f"· '{plan['group']}' 그룹 1개 — 해산합니다",
        "",
        "설치할 때 기재한 것만 걷습니다. 예제를 고쳐 다른 이름으로 저장한 것은 그대로 남습니다.",
        "되돌리기는 다시 설치하기입니다 — 걷은 것을 하나씩 되살리는 길은 없습니다.",
    ])


def remove(
    *,
    file_store,
    hwpx_groups,
    txt_groups,
    hwpx_root: "str | Path",
    txt_root: "str | Path",
    pool_registry,
    data_dir: "str | Path",
) -> dict:
    """manifest 기재분을 걷고 manifest 를 지운다 — 결과 요약 dict 를 돌려준다.

    협력자 주입은 :func:`install` 과 같다. 순서는 **파일 → 고정 → 그룹 → manifest** 다:
    중간에 실패하면 manifest 가 남아 남은 기재를 다시 걷을 수 있다(재시도가 이미 걷은 건을
    「이미 없던 것」으로 정직하게 보고한다). 먼저 지우면 남은 파일의 주소를 잃는다.

    - 템플릿: :meth:`~hwpxfiller.external.template_files.TemplateFileStore.trash` **건별**.
      벌크 이동을 새로 짓지 않는다 — 30일 보존·컷오프 정리는 그 기제가 이미 진 의무다.
    - 데이터: 고정 해제 + 파일 제거. 데이터에는 ``.trash`` 기제가 **없다**(store 의 trash 는
      hwpx·txt 두 매체 루트로만 라우팅한다). 새 휴지통을 지어내는 대신 지운다 — 파일은
      번들 자산의 사본이고 되돌리기가 재설치이므로 잃는 원본이 없다.
    - 고정 해제는 **아직 그 예제 데이터를 가리키는 슬롯**만 건다. 사용자가 그 슬롯을 자기
      데이터로 다시 연결했다면(#67 relink) 그것은 manifest 밖 참조라 남긴다.
    - 그룹: 매체별 :meth:`TemplateGroupModel.disband_group` — 소속만 걷힌다(파일 무관).

    반환: ``{"trashed": [{"media", "path"}], "data_removed", "unpinned", "kept_pins",
    "disbanded", "missing", "group"}``. ``missing`` 은 기재에 있었으나 이미 없던 건이다.
    """
    plan = removal_plan(hwpx_root=hwpx_root, txt_root=txt_root, data_dir=data_dir)
    if plan is None:
        raise ValueError("설치된 예제가 없습니다.")

    trashed: "list[dict]" = []
    missing: "list[str]" = []
    for entry in plan["templates"]:
        path: Path = entry["path"]
        if not path.is_file():  # 사용자가 이미 지웠다 — 재진술하되 실패로 승격하지 않는다
            missing.append(path.name)
            continue
        file_store.trash(entry["media"], path)
        trashed.append({"media": entry["media"], "path": str(path)})

    data_removed = 0
    for path in plan["data_files"]:
        if not path.is_file():
            missing.append(path.name)
            continue
        path.unlink()
        data_removed += 1

    targets = {str(p) for p in plan["data_files"]}
    unpinned = 0
    kept_pins: "list[str]" = []
    for key in plan["pool_keys"]:
        if not pool_registry.exists(key):
            continue  # 사용자가 이미 풀에서 뺐다 — 없는 것을 지웠다고 말하지 않는다
        try:
            item = pool_registry.load(key)
        except ValueError:  # 손상 슬롯 — 남의 것일 수 있으므로 건드리지 않고 남긴다
            kept_pins.append(key)
            continue
        if str(item.opts.get("path", "")) not in targets:
            kept_pins.append(item.name)  # 다른 데이터로 다시 연결된 슬롯 = manifest 밖
            continue
        pool_registry.delete(key)
        unpinned += 1

    group = plan["group"]
    disbanded = hwpx_groups.disband_group(group) + txt_groups.disband_group(group)
    settings.clear_tutorial_manifest()
    return {
        "trashed": trashed,
        "data_removed": data_removed,
        "unpinned": unpinned,
        "kept_pins": kept_pins,
        "disbanded": disbanded,
        "missing": missing,
        "group": group,
    }


def _pin_dataset(pool_registry, path: Path) -> str:
    """예제 CSV 1건을 데이터 풀에 고정하고 슬롯 키를 돌려준다.

    정체성(경로+시트)이 같은 슬롯이 이미 있으면 **새로 만들지 않는다**(레지스트리 불변식:
    같은 데이터 = 슬롯 1개). 재설치는 그 슬롯을 실행 후보로 되돌리기만 한다 — 라벨·메모는
    사용자 것이라 건드리지 않는다.
    """
    found = pool_registry.find_identity(path, "")
    if found is not None:
        key, item = found
        if not item.is_active:
            pool_registry.activate(key)
        return key
    return pool_registry.add(
        DatasetReference(name=path.stem, kind="excel", opts={"path": str(path)})
    )
