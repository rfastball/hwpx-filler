# UI 시안

비교할 시안은 `variants/<id>/index.html`에 둔다. 각 시안은 제품 화면을 독립적으로
구성하되 공통 부팅·브리지·토큰은 `../shared/`에서 참조한다.

새 시안을 추가할 때:

1. 소문자 영문·숫자·하이픈으로 디렉터리 id를 정한다.
2. `variants/<id>/index.html`을 만든다.
3. 루트 `variants.json`에 id·표시명·상태·설명을 등록한다.
4. `run-ui-surface.ps1 -Surface Lab -Variant <id>`로 부팅한다.
5. 시안 하나를 가능한 한 독립된 한 커밋으로 남긴다.

시안끼리 Python 상태 판단을 복제하지 않는다. 공통 브리지는 향후 `shared/`에 한 벌만
추가하고, 각 시안은 같은 스냅샷을 서로 다르게 표현한다.
