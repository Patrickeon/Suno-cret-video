"use client";

import { useState } from "react";
import { Field } from "./ui";
import { getAppToken, inputCls, setAppToken } from "../lib/studio";

/**
 * 접속 토큰 입력 모달.
 *
 * 백엔드(APP_TOKEN 설정된 배포 환경)가 401 을 반환하면 페이지가 이 모달을 띄운다.
 * - 배경: SettingsModal 과 동일한 딤 + 블러 오버레이로 시각 언어 통일.
 * - 닫기 버튼 없음: 토큰 없이는 앱의 어떤 API 도 쓸 수 없으므로
 *   입력을 완료하는 것 외의 탈출구를 주지 않는다 (오버레이 클릭도 무시).
 * - 저장 시 localStorage 에 기록 후 전체 리로드 — 마운트 시점의 초기
 *   fetch(설정/폰트/잡 목록)들이 토큰을 갖고 다시 실행되게 하는 가장 확실한 방법.
 */
export function TokenModal() {
  const [token, setToken] = useState(getAppToken());
  const [saving, setSaving] = useState(false);

  function save() {
    const t = token.trim();
    if (!t) return;
    setSaving(true);
    setAppToken(t);
    window.location.reload();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="w-full max-w-sm space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--modal-bg)] p-6 shadow-2xl">
        <h2 className="text-base font-semibold">🔒 접속 토큰 필요</h2>
        <p className="text-xs leading-relaxed text-[var(--text-dim)]">
          이 서버는 접속 토큰으로 보호되어 있습니다. 배포 시 발급된
          <code className="mx-1 rounded bg-[var(--surface-2)] px-1 py-0.5">APP_TOKEN</code>
          값을 입력하세요. 한 번 입력하면 이 브라우저에 저장됩니다.
        </p>
        <Field label="접속 토큰">
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
            placeholder="토큰 입력…"
            autoFocus
            className={inputCls}
          />
        </Field>
        <div className="flex justify-end">
          <button
            onClick={save}
            disabled={saving || !token.trim()}
            className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50"
          >
            {saving ? "확인 중…" : "입장"}
          </button>
        </div>
      </div>
    </div>
  );
}
