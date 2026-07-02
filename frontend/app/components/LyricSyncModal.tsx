"use client";

import { useEffect, useMemo, useRef, useState } from "react";

function fmtLrc(t: number) {
  const m = Math.floor(t / 60);
  const s = (t - m * 60).toFixed(2).padStart(5, "0");
  return `[${String(m).padStart(2, "0")}:${s}]`;
}

export function LyricSyncModal({
  audio,
  lyrics,
  onApply,
  onClose,
}: {
  audio: File;
  lyrics: string;
  onApply: (lrc: string) => void;
  onClose: () => void;
}) {
  const lines = useMemo(
    () => lyrics.split("\n").map((l) => l.trim()).filter(Boolean),
    [lyrics],
  );
  const url = useMemo(() => URL.createObjectURL(audio), [audio]);
  useEffect(() => () => URL.revokeObjectURL(url), [url]);

  const audioRef = useRef<HTMLAudioElement>(null);
  const [idx, setIdx] = useState(0);
  const [times, setTimes] = useState<(number | null)[]>(() => lines.map(() => null));

  function mark() {
    const a = audioRef.current;
    if (!a) return;
    setTimes((prev) => {
      const n = [...prev];
      n[idx] = a.currentTime;
      return n;
    });
    setIdx((i) => Math.min(i + 1, lines.length - 1));
  }

  // 스페이스바로 현재 줄 마킹
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.code === "Space") {
        e.preventDefault();
        mark();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, lines.length]);

  function buildLrc() {
    return lines
      .map((l, i) => (times[i] != null ? fmtLrc(times[i] as number) : "[00:00.00]") + l)
      .join("\n");
  }

  const done = times.filter((t) => t != null).length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex max-h-[88vh] w-full max-w-lg flex-col gap-3 rounded-2xl border border-[var(--border)] bg-[var(--modal-bg)] p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">🎯 가사 싱크 (탭)</h2>
          <button onClick={onClose} className="text-[var(--text-dim)] hover:text-[var(--text)]">✕</button>
        </div>
        <p className="text-[11px] text-[var(--text-dim)]">
          재생하면서 각 가사가 시작되는 순간 <b>스페이스바</b> 또는 <b>지금</b> 버튼을 누르세요.
          누른 시점이 그 줄의 시작 시간(LRC)이 됩니다.
        </p>

        <audio ref={audioRef} src={url} controls className="w-full" />

        <div className="flex items-center gap-3">
          <button
            onClick={mark}
            className="flex-1 rounded-xl bg-gradient-to-r from-indigo-500 to-fuchsia-500 px-4 py-3 font-semibold text-white transition hover:brightness-110"
          >
            지금 ⏱ (Space)
          </button>
          <span className="text-xs tabular-nums text-[var(--text-dim)]">{done}/{lines.length}</span>
          <button
            onClick={() => { setTimes(lines.map(() => null)); setIdx(0); }}
            className="rounded-lg bg-[var(--surface-2)] px-3 py-2 text-xs text-[var(--text-dim)] hover:bg-[var(--surface-3)]"
          >
            초기화
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-2">
          {lines.map((l, i) => (
            <button
              key={i}
              onClick={() => setIdx(i)}
              className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm ${
                i === idx ? "bg-indigo-500/25 ring-1 ring-indigo-400" : "hover:bg-[var(--surface-3)]"
              }`}
            >
              <span className="w-16 shrink-0 tabular-nums text-[11px] text-[var(--text-faint)]">
                {times[i] != null ? fmtLrc(times[i] as number) : "—"}
              </span>
              <span className="truncate text-[var(--text)]">{l}</span>
            </button>
          ))}
        </div>

        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg bg-[var(--surface-2)] px-4 py-2 text-sm text-[var(--text-dim)] hover:bg-[var(--surface-3)]">
            취소
          </button>
          <button
            onClick={() => onApply(buildLrc())}
            disabled={done === 0}
            className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50"
          >
            LRC 적용
          </button>
        </div>
      </div>
    </div>
  );
}
