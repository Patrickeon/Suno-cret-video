"use client";

import { useEffect, useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

type JobStatus = "queued" | "running" | "done" | "error";
interface Job {
  id: string;
  status: JobStatus;
  error: string | null;
  log: string;
  video: boolean;
  thumb: boolean;
}
interface ChatMsg {
  role: "user" | "assistant";
  text: string;
}

const SUGGESTIONS = [
  "쇼츠 세로형으로 만들어줘",
  "자막을 막대 스펙트럼으로 바꿔줘",
  "배경 켄번스 효과 꺼줘",
  "후렴부터 30초만 잘라줘",
];

export default function Home() {
  const [mode, setMode] = useState<"local" | "ai">("local");

  // 입력
  const [audio, setAudio] = useState<File | null>(null);
  const [lyricsText, setLyricsText] = useState("");
  const [lyricsFile, setLyricsFile] = useState<File | null>(null);
  const [bgFiles, setBgFiles] = useState<File[]>([]);

  // 옵션
  const [viz, setViz] = useState("waves");
  const [shorts, setShorts] = useState(false);
  const [clipStart, setClipStart] = useState("");
  const [clipLen, setClipLen] = useState(30);
  const [kenburns, setKenburns] = useState(true);
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [watermark, setWatermark] = useState("");
  const [align, setAlign] = useState(false);

  // 잡 상태
  const [job, setJob] = useState<Job | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // AI 편집 채팅
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function poll(id: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`${API}/api/jobs/${id}`);
        if (!r.ok) return;
        const j: Job = await r.json();
        setJob(j);
        if (j.status === "done" || j.status === "error") {
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch {
        /* 일시 오류 무시 */
      }
    }, 1500);
  }

  async function generate() {
    setErr("");
    if (!audio) {
      setErr("음원 파일을 선택하세요.");
      return;
    }
    setSubmitting(true);
    setJob(null);
    try {
      const fd = new FormData();
      fd.append("audio", audio);
      if (lyricsFile) fd.append("lyrics_file", lyricsFile);
      if (lyricsText.trim()) fd.append("lyrics_text", lyricsText);
      bgFiles.forEach((f) => fd.append("bg", f));
      fd.append("viz", viz);
      fd.append("shorts", String(shorts));
      fd.append("clip_start", clipStart);
      fd.append("clip_len", String(clipLen));
      fd.append("kenburns", String(kenburns));
      fd.append("title", title);
      fd.append("artist", artist);
      fd.append("watermark", watermark);
      fd.append("align", align ? "auto" : "none");

      const r = await fetch(`${API}/api/render`, { method: "POST", body: fd });
      if (!r.ok) throw new Error(`서버 오류 (${r.status})`);
      const { job_id } = await r.json();
      setJob({ id: job_id, status: "queued", error: null, log: "", video: false, thumb: false });
      poll(job_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "요청 실패");
    } finally {
      setSubmitting(false);
    }
  }

  async function sendAgent() {
    const msg = chatInput.trim();
    if (!msg) return;
    if (!job || job.status !== "done") {
      setMessages((m) => [
        ...m,
        { role: "assistant", text: "⚠ 먼저 '로컬 생성'으로 기본 영상을 만든 뒤 편집을 요청하세요." },
      ]);
      return;
    }
    const history = messages.map((m) => ({ role: m.role, content: m.text }));
    setMessages((m) => [...m, { role: "user", text: msg }]);
    setChatInput("");
    setAgentBusy(true);
    try {
      const r = await fetch(`${API}/api/agent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: job.id, message: msg, history }),
      });
      const data = await r.json();
      if (!r.ok || data.error) throw new Error(data.error || `오류 (${r.status})`);
      setMessages((m) => [...m, { role: "assistant", text: data.reply || "변경을 적용했어요." }]);
      setJob({ id: data.job_id, status: "queued", error: null, log: "", video: false, thumb: false });
      poll(data.job_id);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: "assistant", text: "⚠ " + (e instanceof Error ? e.message : "에이전트 오류") },
      ]);
    } finally {
      setAgentBusy(false);
    }
  }

  const busy = job?.status === "queued" || job?.status === "running";

  return (
    <div className="min-h-full bg-gradient-to-b from-neutral-950 to-neutral-900 text-neutral-100">
      <header className="border-b border-white/10 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🎬</span>
          <h1 className="text-lg font-semibold tracking-tight">Suno MV Studio</h1>
        </div>
        <div className="flex rounded-lg bg-white/5 p-1 text-sm">
          <button
            onClick={() => setMode("local")}
            className={`px-3 py-1.5 rounded-md transition ${mode === "local" ? "bg-white/15 font-medium" : "text-neutral-400 hover:text-neutral-200"}`}
          >
            로컬 생성
          </button>
          <button
            onClick={() => setMode("ai")}
            className={`px-3 py-1.5 rounded-md transition ${mode === "ai" ? "bg-white/15 font-medium" : "text-neutral-400 hover:text-neutral-200"}`}
          >
            AI 편집 ✨
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8 grid gap-8 lg:grid-cols-2">
        {/* 왼쪽: 로컬 폼 또는 AI 채팅 */}
        <section className="space-y-6">
          {mode === "local" ? (
            <>
              <Card title="1. 음원 / 가사">
                <Field label="음원 파일 *">
                  <input type="file" accept="audio/*" onChange={(e) => setAudio(e.target.files?.[0] ?? null)} className={fileCls} />
                </Field>
                <Field label="가사 (텍스트)">
                  <textarea
                    value={lyricsText}
                    onChange={(e) => setLyricsText(e.target.value)}
                    placeholder="한 줄에 한 가사씩 입력하면 곡 길이에 맞춰 자동 분배됩니다."
                    rows={5}
                    className={`${inputCls} resize-y`}
                  />
                </Field>
                <Field label="또는 가사 파일 (.lrc 정확 / .txt)">
                  <input type="file" accept=".lrc,.txt" onChange={(e) => setLyricsFile(e.target.files?.[0] ?? null)} className={fileCls} />
                </Field>
                <label className="flex items-center gap-2 text-sm text-neutral-300">
                  <input type="checkbox" checked={align} onChange={(e) => setAlign(e.target.checked)} />
                  AI 자동 가사 정렬 (백엔드에 stable-ts 필요)
                </label>
              </Card>

              <Card title="2. 배경 / 비주얼">
                <Field label="배경 이미지 (여러 장 = 크로스페이드)">
                  <input type="file" accept="image/*" multiple onChange={(e) => setBgFiles(Array.from(e.target.files ?? []))} className={fileCls} />
                  {bgFiles.length > 0 && <p className="mt-1 text-xs text-neutral-400">{bgFiles.length}개 선택됨</p>}
                </Field>
                <Field label="비주얼라이저">
                  <select value={viz} onChange={(e) => setViz(e.target.value)} className={inputCls}>
                    <option value="waves">파형 (waves)</option>
                    <option value="cqt">막대 스펙트럼 (cqt)</option>
                    <option value="spectrum">스펙트럼 (spectrum)</option>
                    <option value="none">없음</option>
                  </select>
                </Field>
                <label className="flex items-center gap-2 text-sm text-neutral-300">
                  <input type="checkbox" checked={kenburns} onChange={(e) => setKenburns(e.target.checked)} />
                  배경 켄 번스(줌·팬) 효과
                </label>
              </Card>

              <Card title="3. 포맷 / 메타">
                <label className="flex items-center gap-2 text-sm text-neutral-300">
                  <input type="checkbox" checked={shorts} onChange={(e) => setShorts(e.target.checked)} />
                  쇼츠 세로형 (9:16, 1080×1920)
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="클립 시작 (mm:ss, 선택)">
                    <input value={clipStart} onChange={(e) => setClipStart(e.target.value)} placeholder="예: 1:05" className={inputCls} />
                  </Field>
                  <Field label="클립 길이(초)">
                    <input type="number" value={clipLen} onChange={(e) => setClipLen(Number(e.target.value))} className={inputCls} />
                  </Field>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="제목 (썸네일)">
                    <input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} />
                  </Field>
                  <Field label="아티스트">
                    <input value={artist} onChange={(e) => setArtist(e.target.value)} className={inputCls} />
                  </Field>
                </div>
                <Field label="워터마크 (우하단)">
                  <input value={watermark} onChange={(e) => setWatermark(e.target.value)} placeholder="@내채널" className={inputCls} />
                </Field>
              </Card>

              {err && <p className="text-sm text-red-400">{err}</p>}

              <button
                onClick={generate}
                disabled={submitting || busy}
                className="w-full rounded-xl bg-indigo-500 px-4 py-3 font-semibold text-white transition hover:bg-indigo-400 disabled:opacity-50"
              >
                {busy ? "렌더링 중…" : "🎬 뮤직비디오 생성"}
              </button>
            </>
          ) : (
            <Card title="AI 편집 ✨">
              <p className="text-xs text-neutral-400">
                먼저 <b>로컬 생성</b>으로 기본 영상을 만든 뒤, 여기서 자연어로 수정을 요청하세요.
                {!job && <span className="text-amber-300"> (현재 편집할 프로젝트가 없습니다)</span>}
              </p>

              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => setChatInput(s)}
                    className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-neutral-300 hover:bg-white/10"
                  >
                    {s}
                  </button>
                ))}
              </div>

              <div className="h-72 space-y-3 overflow-y-auto rounded-lg bg-black/30 p-3">
                {messages.length === 0 && (
                  <p className="text-xs text-neutral-500">예: &ldquo;쇼츠로 만들어줘&rdquo;, &ldquo;스펙트럼으로 바꿔줘&rdquo;</p>
                )}
                {messages.map((m, i) => (
                  <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
                    <span
                      className={`inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
                        m.role === "user" ? "bg-indigo-500/80 text-white" : "bg-white/10 text-neutral-100"
                      }`}
                    >
                      {m.text}
                    </span>
                  </div>
                ))}
                {agentBusy && <p className="text-xs text-neutral-400">에이전트가 생각 중…</p>}
              </div>

              <div className="flex gap-2">
                <input
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !agentBusy && sendAgent()}
                  placeholder="예: 자막 더 크게, 후렴부터 쇼츠로…"
                  className={inputCls}
                />
                <button
                  onClick={sendAgent}
                  disabled={agentBusy}
                  className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50"
                >
                  보내기
                </button>
              </div>
            </Card>
          )}
        </section>

        {/* 오른쪽: 결과 */}
        <section className="space-y-4">
          <Card title="결과 미리보기">
            {!job && <p className="text-sm text-neutral-400">왼쪽에서 입력 후 생성을 누르면 여기에 영상이 나옵니다.</p>}

            {job && busy && (
              <div className="flex items-center gap-3 text-sm text-neutral-300">
                <span className="h-3 w-3 animate-pulse rounded-full bg-indigo-400" />
                {job.status === "queued" ? "대기 중…" : "렌더링 중…"} (job {job.id})
              </div>
            )}

            {job?.status === "error" && (
              <div className="space-y-2">
                <p className="text-sm text-red-400">렌더 실패: {job.error}</p>
                {job.log && (
                  <pre className="max-h-48 overflow-auto rounded-lg bg-black/40 p-3 text-xs whitespace-pre-wrap text-neutral-400">
                    {job.log}
                  </pre>
                )}
              </div>
            )}

            {job?.status === "done" && job.video && (
              <div className="space-y-3">
                <video
                  src={`${API}/api/jobs/${job.id}/video`}
                  controls
                  className={`w-full rounded-lg bg-black ${shorts ? "mx-auto max-h-[70vh] aspect-[9/16]" : "aspect-video"}`}
                />
                <div className="flex flex-wrap gap-3 text-sm">
                  <a href={`${API}/api/jobs/${job.id}/video`} download className="rounded-lg bg-white/10 px-3 py-2 hover:bg-white/20">
                    ⬇ 영상 다운로드
                  </a>
                  {job.thumb && (
                    <a href={`${API}/api/jobs/${job.id}/thumb`} download className="rounded-lg bg-white/10 px-3 py-2 hover:bg-white/20">
                      ⬇ 썸네일 다운로드
                    </a>
                  )}
                </div>
              </div>
            )}
          </Card>

          {job?.thumb && job.status === "done" && (
            <Card title="썸네일">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`${API}/api/jobs/${job.id}/thumb`} alt="thumbnail" className="w-full rounded-lg" />
            </Card>
          )}
        </section>
      </main>
    </div>
  );
}

const inputCls =
  "w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none focus:border-indigo-400";
const fileCls =
  "block w-full text-sm text-neutral-300 file:mr-3 file:rounded-md file:border-0 file:bg-white/10 file:px-3 file:py-2 file:text-neutral-100 hover:file:bg-white/20";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-5 space-y-4">
      <h2 className="text-sm font-semibold text-neutral-200">{title}</h2>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-neutral-400">{label}</span>
      {children}
    </label>
  );
}
