"""데이터셋 풀 — 구현이 이 모듈을 떠난 자리(P2-22 #570, 정의 0 stub).

권위는 다음으로 갈라져 이관됐다:

- 값·수명·정체성(``DatasetReference``·``excel_identity``·``reference_identity``·
  ``STATUS_*``): :mod:`hwpxfiller.domain.dataset_reference`
- JSON 파일 레지스트리·persistence codec(``save_reference``/``load_reference``)·
  불투명 슬롯 키·공유 쓰기 잠금·확정 결속 semantic op(``DatasetPoolRegistry``):
  :mod:`hwpxfiller.external.dataset_store`
- 기본 위치 해석(``~/.hwpxfiller/datasets``):
  :func:`hwpxfiller.host.locations.default_dataset_pool_dir`
- Application port·뷰모델·확정 결속 지문(``DatasetPoolPort``·``DatasetPoolViewModel``·
  ``bound_state``/``confirm_basis``): :mod:`hwpxfiller.application.dataset_pool`

core(안쪽)는 external 을 import 할 수 없으므로 재수출 facade 를 두지 않는다 — 소비자는
전부 새 정본으로 전환됐고, 이 파일은 ring 유닛 좌표(``docs/module_rings.toml`` 의
``hwpxfiller.core.dataset_pool``)를 보존하기 위해 남는다. 구
``DatasetPoolItem(DatasetReference)`` persistence subclass 는 최종형이 아니라서 승계
없이 폐기됐다(#570 persistence model 규율) — 저장 bytes·JSON schema·슬롯 키·legacy
slug-file 호환은 새 정본이 그대로 보존한다.
"""
