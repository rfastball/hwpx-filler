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

  function chained(key, send) {
    // `return tail` 금지 — 자기 자신으로 resolve 하면 체인 순환(TypeError)으로 영영 안 끝난다.
    const tail = (CALL_CHAINS.get(key) || Promise.resolve()).then(send).then(() => {
      if (CALL_CHAINS.get(key) === tail) CALL_CHAINS.delete(key);
    });
    CALL_CHAINS.set(key, tail);
    return tail;
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

  window.Intent = { chained, createFavorite };
})();
