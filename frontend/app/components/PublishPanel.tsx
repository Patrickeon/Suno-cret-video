"use client";

import { useState } from "react";
import { API, inputCls } from "../lib/studio";

interface Chapter { time: string; label: string; }
interface Meta {
  title?: string;
  description?: string;
  tags?: string[];
  chapters?: Chapter[];
}

export function PublishPanel({
  jobId,
  llmKeySet,
  onToast,
  onRefresh,
}: {
  jobId: string;
  llmKeySet: boolean;
  onToast: (text: string, kind?: "info" | "success" | "error") => void;
  onRefresh: () => void;
}) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaBusy, setMetaBusy] = useState(false);
  const [count, setCount] = useState(3);
  const [batchBusy, setBatchBusy] = useState(false);

  async function genMeta() {
    setMetaBusy(true);
    try {
      const r = await fetch(`${API}/api/metadata`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId }),
      });
      const data = await r.json();
      if (!r.ok || data.error) throw new Error(data.error || `오류 (${r.status})`);
      setMeta(data);
      onToast("메타데이터를 생성했어요.", "success");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "메타데이터 생성 실패", "error");
    } finally {
      setMetaBusy(false);
    }
  }

  async function runBatch() {
    setBatchBusy(true);
    try {
      const r = await fetch(`${API}/api/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId, shorts_count: count }),
      });
      const data = await r.json();
      if (!r.ok || data.error) throw new Error(data.error || `오류 (${r.status})`);
      onToast(`롱폼 1 + 쇼츠 ${data.detected}개 렌더 시작! '최근 작업'에서 확인하세요.`, "success");
      onRefresh();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "배치 실패", "error");
    } finally {
      setBatchBusy(false);
    }
  }

  function copy(text: string) {
    navigator.clipboard?.writeText(text).then(
      () => onToast("복사됨", "info"),
      () => onToast("복사 실패", "error"),
    );
  }

  const descBlock = meta
    ? [
        meta.description || "",
        meta.chapters && meta.chapters.length
          ? "\n\n⏱️ 챕터\n" + meta.chapters.map((c) => `${c.time} ${c.label}`).join("\n")
          : "",
        meta.tags && meta.tags.length ? "\n\n" + meta.tags.map((t) => `#${t}`).join(" ") : "",
      ].join("")
    : "";

  return (
    <div className="space-y-4">
      {/* 메타데이터 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-neutral-400">제목 · 설명 · 태그</span>
          <button
            onClick={genMeta}
            disabled={metaBusy || !llmKeySet}
            title={llmKeySet ? "" : "⚙️ 설정에서 Claude 키 필요"}
            className="rounded-lg bg-indigo-500/80 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {metaBusy ? "생성 중…" : "✨ 메타데이터 생성"}
          </button>
        </div>
        {!llmKeySet && (
          <p className="text-[11px] text-amber-300">⚙️ 설정에서 Claude 키를 넣으면 자동 생성됩니다.</p>
        )}
        {meta && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <input readOnly value={meta.title || ""} className={inputCls} />
              <button onClick={() => copy(meta.title || "")} className="shrink-0 rounded-lg bg-white/10 px-3 py-2 text-xs hover:bg-white/20">복사</button>
            </div>
            <div className="flex items-start gap-2">
              <textarea readOnly value={descBlock} rows={6} className={`${inputCls} resize-y`} />
              <button onClick={() => copy(descBlock)} className="shrink-0 rounded-lg bg-white/10 px-3 py-2 text-xs hover:bg-white/20">복사</button>
            </div>
          </div>
        )}
      </div>

      {/* 롱폼 + 쇼츠 배치 */}
      <div className="space-y-2 border-t border-white/10 pt-3">
        <span className="text-xs font-medium text-neutral-400">롱폼 + 쇼츠 자동 배치</span>
        <p className="text-[11px] text-neutral-500">
          후렴(가장 큰 구간)을 자동으로 찾아 세로 쇼츠로 잘라냅니다. 롱폼 1개와 함께 한 번에 렌더돼요.
        </p>
        <div className="flex items-center gap-2">
          <label className="text-xs text-neutral-400">쇼츠 개수</label>
          <input
            type="number"
            min={0}
            max={6}
            value={count}
            onChange={(e) => setCount(Math.max(0, Math.min(6, Number(e.target.value))))}
            className={`${inputCls} w-20`}
          />
          <button
            onClick={runBatch}
            disabled={batchBusy}
            className="ml-auto rounded-lg bg-fuchsia-500 px-3 py-2 text-xs font-medium text-white hover:bg-fuchsia-400 disabled:opacity-50"
          >
            {batchBusy ? "시작 중…" : "🎬 롱폼+쇼츠 생성"}
          </button>
        </div>
      </div>
    </div>
  );
}
