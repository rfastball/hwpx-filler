/* 삭제 직후 복원 1슬롯 파사드 (R3-01 · #410) — DOM·타이머·버튼 배선은 React host
   (src/overlay/host.ts)가 소유하고, 여기는 표면과 host 부재의 안전측 재진술만 남는다.
   새 삭제가 이전 콜백을 덮고, 10초 뒤 어포던스만 닫힌다(host 이식 거동 — 실제 파일은
   백엔드 .trash에 30일 남으므로 앱 종료가 곧 즉시 영구 삭제는 아니다). */
import { overlayDialogHost } from "../src/overlay/instance.ts";

function show(message, callback) {
  const host = overlayDialogHost();
  if (host === null) {
    // host 부재(부팅 창·마운트 실패)에 어포던스를 조용히 삼키지 않는다 — 삭제는 이미
    // 일어났으므로 메시지만이라도 시끄럽게 남긴다(confirm-or-alarm).
    console.error("UndoToast: host 부재 — 되돌리기 어포던스 없이 재진술합니다.");
    window.alert(message);
    return;
  }
  host.toastShow(message, callback);
}

function hide() {
  const host = overlayDialogHost();
  if (host !== null) host.toastHide();
}

export const UndoToast = { show, hide };
