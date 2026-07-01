"use client";

import { useEffect, useState } from "react";
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
  const [batchIds, setBatchIds] = useState<string[]>([]);

  // YouTube 업로드
  const [ytReady, setYtReady] = useState(false);
  const [ytPrivacy, setYtPrivacy] = useState("private");
  const [ytBusy, setYtBusy] = useState(false);
  const [ytUrl, setYtUrl] = useState("");

  useEffect(() => {
    fetch(`${API}/api/youtube/status`)
      .then((r) => r.json())
      .then((d) => setYtReady(!!d.token))
      .catch(() => {});
  }, []);

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
      setBatchIds([data.longform, ...(data.shorts || [])].filter(Boolean));
      onToast(`롱폼 1 + 쇼츠 ${data.detected}개 렌더 시작! '최근 작업'에서 확인하세요.`, "success");
      onRefresh();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "배치 실패", "error");
    } finally {
      setBatchBusy(false);
    }
  }

  async function uploadYouTube() {
    setYtBusy(true);
    setYtUrl("");
    try {
      const r = await fetch(`${API}/api/youtube/upload`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: jobId,
          title: meta?.title || "뮤직비디오",
          description: (meta?.description || "") +
            (meta?.tags?.length ? "\n\n" + meta.tags.map((t) => `#${t}`).join(" ") : ""),
          tags: meta?.tags || [],
          privacy: ytPrivacy,
        }),
      });
      const data = await r.json();
      if (!r.ok || data.error) throw new Error(data.error || `오류 (${r.status})`);
      setYtUrl(data.url);
      onToast("업로드 완료!", "success");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "업로드 실패", "error");
    } finally {
      setYtBusy(false);
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
          <span className="text-xs font-medium text-[var(--text-dim)]">제목 · 설명 · 태그</span>
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
              <button onClick={() => copy(meta.title || "")} className="shrink-0 rounded-lg bg-[var(--surface-2)] px-3 py-2 text-xs hover:bg-[var(--surface-3)]">복사</button>
            </div>
            <div className="flex items-start gap-2">
              <textarea readOnly value={descBlock} rows={6} className={`${inputCls} resize-y`} />
              <button onClick={() => copy(descBlock)} className="shrink-0 rounded-lg bg-[var(--surface-2)] px-3 py-2 text-xs hover:bg-[var(--surface-3)]">복사</button>
            </div>
          </div>
        )}
      </div>

      {/* 롱폼 + 쇼츠 배치 */}
      <div className="space-y-2 border-t border-[var(--border)] pt-3">
        <span className="text-xs font-medium text-[var(--text-dim)]">롱폼 + 쇼츠 자동 배치</span>
        <p className="text-[11px] text-[var(--text-faint)]">
          후렴(가장 큰 구간)을 자동으로 찾아 세로 쇼츠로 잘라냅니다. 롱폼 1개와 함께 한 번에 렌더돼요.
        </p>
        <div className="flex items-center gap-2">
          <label className="text-xs text-[var(--text-dim)]">쇼츠 개수</label>
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
        {batchIds.length > 0 && (
          <a
            href={`${API}/api/jobs/zip?ids=${batchIds.join(",")}`}
            className="inline-block rounded-lg bg-[var(--surface-2)] px-3 py-2 text-xs text-[var(--text)] hover:bg-[var(--surface-3)]"
          >
            📦 완료분 전체 ZIP 다운로드
          </a>
        )}
      </div>

      {/* YouTube 업로드 */}
      <div className="space-y-2 border-t border-[var(--border)] pt-3">
        <span className="text-xs font-medium text-[var(--text-dim)]">YouTube 업로드</span>
        {!ytReady ? (
          <p className="text-[11px] text-[var(--text-faint)]">
            연결되지 않았습니다. <code className="text-[var(--text-dim)]">backend/yt_upload.py</code> 안내대로
            OAuth 설정 후 <code className="text-[var(--text-dim)]">python -m yt_upload</code> 로 1회 인증하면 활성화됩니다.
          </p>
        ) : (
          <div className="flex items-center gap-2">
            <select value={ytPrivacy} onChange={(e) => setYtPrivacy(e.target.value)} className={`${inputCls} w-32`}>
              <option value="private">비공개</option>
              <option value="unlisted">미등록</option>
              <option value="public">공개</option>
            </select>
            <button
              onClick={uploadYouTube}
              disabled={ytBusy}
              className="ml-auto rounded-lg bg-red-500 px-3 py-2 text-xs font-medium text-white hover:bg-red-400 disabled:opacity-50"
            >
              {ytBusy ? "업로드 중…" : "▶ 유튜브 업로드"}
            </button>
          </div>
        )}
        {ytUrl && (
          <a href={ytUrl} target="_blank" rel="noreferrer" className="block text-xs text-indigo-300 hover:underline">
            {ytUrl}
          </a>
        )}
      </div>
    </div>
  );
}
