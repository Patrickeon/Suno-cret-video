"use client";

const STEPS = [
  {
    icon: "①",
    title: "음원 · 가사 올리기",
    body: "음원(mp3·wav·flac)은 필수예요. 가사는 텍스트로 붙여넣거나 .lrc/.txt 파일로 올립니다. .lrc면 정확한 싱크, 텍스트만 주면 곡 길이에 맞춰 자동 분배됩니다.",
  },
  {
    icon: "②",
    title: "배경 · 비주얼 고르기",
    body: "빠른 프리셋(🌙Lo-fi · 🎹발라드 · ⚡EDM · ◾미니멀)으로 한 번에 설정하거나, 배경 이미지를 올리고(여러 장이면 크로스페이드) 비주얼라이저·켄번스를 직접 조절하세요.",
  },
  {
    icon: "③",
    title: "포맷 · 메타 설정",
    body: "쇼츠(9:16) 여부, 클립 구간(후렴만 자르기), 썸네일 제목·아티스트, 워터마크를 정합니다.",
  },
  {
    icon: "🎬",
    title: "생성하고 받기",
    body: "‘뮤직비디오 생성’을 누르면 오른쪽에 진행률(%)이 실시간으로 차오릅니다. 끝나면 영상·썸네일을 바로 다운로드할 수 있어요.",
  },
  {
    icon: "✨",
    title: "AI 편집 (선택)",
    body: "기본 영상을 만든 뒤 ‘AI 편집’ 탭에서 ‘쇼츠로 만들어줘’, ‘스펙트럼으로 바꿔줘’처럼 자연어로 수정하면 옵션을 바꿔 다시 렌더합니다. (⚙️에 Claude 키 필요)",
  },
  {
    icon: "🎥",
    title: "AI 배경 영상 (선택)",
    body: "AI 편집 탭의 ‘AI 배경 영상’에 프롬프트를 넣으면 AI가 영상 클립을 만들어 배경에 깔고 그 위에 비주얼라이저·자막을 얹어 재렌더합니다. (⚙️에 영상 provider 키 필요)",
  },
];

export function HelpModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="max-h-[85vh] w-full max-w-lg space-y-4 overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--modal-bg)] p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">❓ 사용법</h2>
          <button onClick={onClose} className="text-[var(--text-dim)] hover:text-[var(--text)]">✕</button>
        </div>
        <p className="text-xs text-[var(--text-dim)]">
          음원 + 가사를 올리면 영상·자막·썸네일이 한 번에 나오는 뮤직비디오 스튜디오입니다.
        </p>
        <ol className="space-y-3">
          {STEPS.map((s) => (
            <li key={s.title} className="flex gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-3">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-sm">
                {s.icon}
              </span>
              <div className="space-y-0.5">
                <h3 className="text-sm font-medium text-[var(--text)]">{s.title}</h3>
                <p className="text-xs leading-relaxed text-[var(--text-dim)]">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-xs text-amber-200/90">
          💡 팁: AI 기능(편집·배경 영상)은 우측 상단 <b>⚙️ 설정</b>에서 API 키를 먼저 넣어야 동작합니다.
          기본 영상 생성은 키 없이도 됩니다.
        </div>
      </div>
    </div>
  );
}
