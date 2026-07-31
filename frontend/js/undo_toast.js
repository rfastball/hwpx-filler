/* 삭제 직후 복원 1슬롯 표면. 새 삭제가 이전 콜백을 덮고, 10초 뒤 어포던스만 닫힌다.
   실제 파일은 백엔드 .trash에 30일 남으므로 앱 종료이 곧 즉시 영구 삭제는 아니다. */
(function () {
  let undo = null;
  let timer = null;

  function hide() {
    document.getElementById("undoToast").hidden = true;
    undo = null;
    if (timer) clearTimeout(timer);
    timer = null;
  }

  function show(message, callback) {
    const toast = document.getElementById("undoToast");
    document.getElementById("undoToastText").textContent = message;
    undo = callback;
    toast.hidden = false;
    if (timer) clearTimeout(timer);
    timer = setTimeout(hide, 10000);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("undoToastBtn").addEventListener("click", async function () {
      const action = undo;
      if (!action) return;
      this.disabled = true;
      try { await action(); hide(); }
      catch (err) { window.alert(String((err && err.message) || err)); }
      finally { this.disabled = false; }
    });
  });

  window.UndoToast = { show, hide };
})();
