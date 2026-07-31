/* 지연 왕복 중의 **의도** — 브리지 호출 직렬화 + 즐겨찾기 미결 의도. 공용 단일 출처.

   지도 §8.4 4행이 세운 축이다: "축은 값 하나가 아니라 네 개의 계약면"의 네 번째 면
   (지연 왕복 중의 의도). 「작업」 화면이 리뷰 3R·4R·5R·6R 를 거쳐 이 기제를 세웠는데,
   재작성 F2 의 라이브러리가 같은 별을 새로 그리면서 **기제 없이 DOM 값만 실어 보냈다** —
   같은 결함류가 표면을 넘어 재발했다(리뷰 3R). 점별로 한 벌 더 짜는 대신 기제를 여기로
   걷어 두 표면이 한 몸통을 쓴다(grouplist.js·popover.js·datazone.js 선례).

   판정·영속은 여전히 Python 몫이다 — 여기서 하는 것은 "무엇을 보낼지"의 계산과 "언제
   보낼지"의 순서뿐이다. */
(function () {
  /* 브리지 호출 직렬화 — 키 하나당 체인 하나. pywebview 는 호출마다 별도 스레드라 동시
     발신은 **도착 순서를 보장하지 않는다**: 즐겨찾기는 나중 클릭과 반대 상태가 영속될 수
     있고, 탐색 검색은 늦게 도착한 옛 응답이 새 검색 결과를 되돌린다. */
  const CALL_CHAINS = new Map();

  /* **저장되는 링은 절대 reject 하지 않는다**(리뷰 5R). 실패한 promise 를 체인에 남기면 이후
     같은 키의 모든 호출이 그 rejected 링에 `.then(send)` 로 붙어 **영영 실행되지 않는다** —
     접힘 영속이 한 번 실패했다고 그 화면의 탭·검색·필터가 세션 내내 죽는다.

     즐겨찾기 소비처는 `send` 안에서 스스로 잡아 이 함정을 우연히 피해 있었고, 그래서 기제가
     "호출자가 반드시 잡는다"는 암묵 계약 위에 서 있었다 — 라이브러리 축(4R)이 맨 `Bridge.call`
     을 넘기며 그 계약을 밟았다. 암묵 계약은 언젠가 밟힌다: 기제 쪽에서 끊는다.

     호출자에게는 **실패를 그대로 전한다**(`result` 반환) — 되돌리기·loud 재진술은 여전히
     호출자 몫이고(GroupList.toggleGroup 이 그렇게 쓴다), 아무도 안 잡으면 셸 백스톱이 말한다. */
  function chained(key, send) {
    const result = (CALL_CHAINS.get(key) || Promise.resolve()).then(send);
    // `return tail` 금지 — 자기 자신으로 resolve 하면 체인 순환(TypeError)으로 영영 안 끝난다.
    const tail = result.catch(() => {}).then(() => {
      if (CALL_CHAINS.get(key) === tail) CALL_CHAINS.delete(key);
    });
    CALL_CHAINS.set(key, tail);
    return result;
  }

  /* 큐에 든 발신이 **전부 착지할 때까지** 기다린다 — 합류하지 않고 기다리기만 한다.
     ``chained`` 가 「쓰기끼리의 순서」를 정한다면 이쪽은 「**읽기가 쓰기 뒤에 온다**」를 정한다.

     **왜 별도의 계약면인가**(F6 8R P1). 한 사용자 동작이 브리지 호출 **둘로 쪼개지는** 자리가
     있다: 값 칸에 타이핑하고 곧바로 「복사」를 누르면 blur 가 `set_map_value` 를 쏘고 클릭이
     `copy_precheck` 를 쏜다. pywebview 는 호출마다 별도 스레드라 **도착 순서가 정의되지
     않는다** — 복사가 이기면 화면엔 방금 친 값이 보이는데 클립보드엔 **이전 값**이 나가고,
     이탈 가드가 이기면 「잃을 것 없음」을 답한 뒤 그 편집이 조용히 사라진다.

     백엔드 잠금으로는 못 닫는다(F6 3R·5R·7R 가 그 층에서 세 번 시도했다): 잠금은 겹치지
     않게 할 뿐 **누가 먼저인지**는 안 정하고, 먼저 잡는 쪽이 이긴다. 순서는 쏘는 쪽에서만
     정할 수 있다.

     그래서 규약은 하나다 — **같은 상태를 바꾸는 발신은 한 체인, 그 상태를 읽는 커밋은 그
     체인을 먼저 정산한다.** 「기안」이 자기 안에 지어 둔 `flushDeb` 이 같은 술어이고
     (디바운스 타이머까지 함께 발사한다는 점만 더한다), 이 함수는 그것의 공용 판이다.

     정산 뒤에 새 발신이 끼어들 창은 없다: JS 는 단일 스레드라 `await` 이 재개되는 마이크로태스크
     와 이어지는 호출 사이에 사용자 입력이 들어가지 못한다. */
  function settle(key) {
    return CALL_CHAINS.get(key) || Promise.resolve();
  }

  /* 미결 의도는 **모듈 스코프**다 — 표면마다 사본을 두면 "공용 몸통"이 이름뿐이 된다
     (리뷰 4R). 라이브러리에서 별을 켠 직후 「작업」 화면으로 넘어가 아직 갱신 안 된 빈 별을
     누르면, 사본이 갈린 경우 두 인스턴스가 똑같이 `true` 를 계산해 같은 쓰기가 두 번 나가고
     **두 번째 토글이 사라진다**. 키가 작업 이름이라 공유가 곧 옳은 의미다 — 쓰기 체인이
     이미 전역 하나인 것과 같은 이유다(즐겨찾기 시각은 작업들 사이의 순위). */
  const FAV_PENDING = new Map();  // 작업 이름 → 왕복 중인(또는 대기 중인) 의도 상태
  const FAV_LAST = new Map();     // 작업 이름 → 그 작업이 마지막으로 큐에 든 링(정리 식별)

  /* 즐겨찾기 전이 몸통 — 낙관 표지 없이 Python 왕복 결과(push)로만 표시가 바뀐다. 별이 먼저
     켜졌다가 저장 실패로 되돌아가면 영속된 척하는 거짓 표지다(#215 동류).

     **의도 직렬화**: 표시는 왕복 뒤에 바뀌므로, 왕복 중 두 번째 클릭이 DOM 의 낡은 상태를
     읽으면 같은 의도를 두 번 보낸다 — `set_favorite` 은 재지정을 멱등 처리하니 껐다 켠 것이
     아니라 **켜진 채로 남는다**(사용자 의도 소실). 그래서 다음 값은 DOM 이 아니라 **미결
     의도**에서 계산한다.

     **쓰기 직렬화**: 의도를 옳게 계산해도 왕복을 동시에 띄우면 안 된다 — 나중 클릭의 쓰기가
     먼저 레지스트리 잠금을 잡으면 **마지막 클릭과 반대 상태가 영속된다**. 체인은 작업별이
     아니라 **전역 하나**다: 서로 다른 작업 둘을 연속으로 별 찍을 때도 클릭 순서가 곧 쓰기
     순서여야 한다(시각은 Python 이 잠금 안에서 찍는다).

     `cfg` = {send(name, value) → Promise, onError(message)}. 소비 표면은 브리지 왕복과
     오류 표면(로그/alert)만 주입한다 — 그 둘이 표면마다 정당하게 다른 전부다. */
  function createFavorite(cfg) {
    function pending(name, domPressed) {
      return FAV_PENDING.has(name) ? FAV_PENDING.get(name) : domPressed;
    }

    function toggle(name, domPressed) {
      const value = !pending(name, domPressed);
      FAV_PENDING.set(name, value);
      const send = () => Promise.resolve(cfg.send(name, value)).catch((err) => {
        cfg.onError("즐겨찾기 변경 실패: " + String((err && err.message) || err));
      });
      // 체인 링은 절대 reject 하지 않는다(send 안 catch) — 한 번 실패해도 뒤 클릭이 막히지 않게.
      // 정리는 **꼬리 식별**로 판정한다: 값 비교로는 true→false→true 처럼 같은 값이 다시 큐에
      // 있을 때 첫 왕복 완료가 최신 의도를 지운다. 그러면 뒤 클릭이 (스냅샷이 아직 없는) 낡은
      // DOM 을 읽어 의도가 어긋난다. 이 링이 마지막으로 큐에 든 것일 때만 걷는다.
      const tail = chained("favorite", send).then(() => {
        if (FAV_PENDING.get(name) === value && FAV_LAST.get(name) === tail) {
          FAV_PENDING.delete(name);
          FAV_LAST.delete(name);
        }
      });
      FAV_LAST.set(name, tail);  // 작업별 "마지막으로 큐에 든 링" — 정리 식별
      return tail;
    }

    return { toggle, pending };
  }

  window.Intent = { chained, settle, createFavorite };
})();
