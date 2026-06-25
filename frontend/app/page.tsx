"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
interface JobSummary {
  id: string;
  status: JobStatus;
  video: boolean;
  thumb: boolean;
  created: number;
  title: string;
  shorts: boolean;
}
interface ChatMsg {
  role: "user" | "assistant";
  text: string;
}
interface Settings {
  llm_provider: string;
  llm_model: string;
  llm_key_set: boolean;
  video_provider: string;
  video_key_set: boolean;
}
interface Toast {
  id: number;
  text: string;
  kind: "info" | "success" | "error";
}

const SUGGESTIONS = [
  "쇼츠 세로형으로 만들어줘",
  "막대 스펙트럼으로 바꿔줘",
  "배경 켄번스 꺼줘",
  "후렴부터 30초만 잘라줘",
];

let toastSeq = 0;

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

  // 잡 / 결과
  const [job, setJob] = useState<Job | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [recent, setRecent] = useState<JobSummary[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // AI 채팅
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);

  // 설정 / 토스트
  const [showSettings, setShowSettings] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((text: string, kind: Toast["kind"] = "info") => {
    const id = ++toastSeq;
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);

  const refreshRecent = useCallback(() => {
    fetch(`${API}/api/jobs`)
      .then((r) => r.json())
      .then((d) => setRecent(d.jobs ?? []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch(`${API}/api/settings`).then((r) => r.json()).then(setSettings).catch(() => {});
    refreshRecent();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refreshRecent]);

  // 미리보기 URL
  const audioUrl = useMemo(() => (audio ? URL.createObjectURL(audio) : ""), [audio]);
  const bgUrls = useMemo(() => bgFiles.map((f) => URL.createObjectURL(f)), [bgFiles]);
  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl); }, [audioUrl]);
  useEffect(() => () => { bgUrls.forEach((u) => URL.revokeObjectURL(u)); }, [bgUrls]);

  async function saveSettings(patch: Record<string, string>) {
    const r = await fetch(`${API}/api/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    setSettings(await r.json());
    toast("설정이 저장되었습니다.", "success");
  }

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
          refreshRecent();
          toast(j.status === "done" ? "렌더 완료 ✓" : "렌더 실패", j.status === "done" ? "success" : "error");
        }
      } catch {
        /* 일시 오류 무시 */
      }
    }, 1500);
  }

  async function generate() {
    if (!audio) {
      toast("음원 파일을 선택하세요.", "error");
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
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `서버 오류 (${r.status})`);
      setJob({ id: data.job_id, status: "queued", error: null, log: "", video: false, thumb: false });
      poll(data.job_id);
      toast("렌더를 시작했어요.", "info");
    } catch (e) {
      toast(e instanceof Error ? e.message : "요청 실패", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function sendAgent() {
    const msg = chatInput.trim();
    if (!msg) return;
    if (!job || job.status !== "done") {
      toast("먼저 '로컬 생성'으로 기본 영상을 만든 뒤 편집을 요청하세요.", "error");
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
      setMessages((m) => [...m, { role: "assistant", text: "⚠ " + (e instanceof Error ? e.message : "에이전트 오류") }]);
    } finally {
      setAgentBusy(false);
    }
  }

  async function openJob(id: string) {
    try {
      const j: Job = await (await fetch(`${API}/api/jobs/${id}`)).json();
      setJob(j);
    } catch {
      toast("불러오기 실패", "error");
    }
  }

  const busy = job?.status === "queued" || job?.status === "running";

  return (
    <div className="min-h-full bg-[radial-gradient(80%_60%_at_50%_-10%,#1e1b4b_0%,#0a0a0f_55%)] text-neutral-100">
      {/* 토스트 */}
      <div className="fixed right-4 top-4 z-[60] flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`rounded-lg px-4 py-2.5 text-sm shadow-lg backdrop-blur ${
              t.kind === "success"
                ? "bg-emerald-500/90"
                : t.kind === "error"
                ? "bg-red-500/90"
                : "bg-white/15"
            }`}
          >
            {t.text}
          </div>
        ))}
      </div>

      <header className="sticky top-0 z-40 border-b border-white/10 bg-black/30 px-6 py-3.5 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-lg shadow-lg">
              🎬
            </span>
            <div>
              <h1 className="text-base font-semibold leading-tight tracking-tight">Suno MV Studio</h1>
              <p className="text-[11px] text-neutral-400">음원 + 가사 → AI 뮤직비디오</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex rounded-lg bg-white/5 p-1 text-sm ring-1 ring-white/10">
              <button
                onClick={() => setMode("local")}
                className={`rounded-md px-3 py-1.5 transition ${mode === "local" ? "bg-white/15 font-medium" : "text-neutral-400 hover:text-neutral-200"}`}
              >
                로컬 생성
              </button>
              <button
                onClick={() => setMode("ai")}
                className={`rounded-md px-3 py-1.5 transition ${mode === "ai" ? "bg-white/15 font-medium" : "text-neutral-400 hover:text-neutral-200"}`}
              >
                AI 편집 ✨
              </button>
            </div>
            <button
              onClick={() => setShowSettings(true)}
              title="API 키 설정"
              className="rounded-lg bg-white/5 px-3 py-1.5 text-sm text-neutral-300 ring-1 ring-white/10 hover:bg-white/10"
            >
              ⚙️
              {settings && (settings.llm_key_set || settings.video_key_set) && (
                <span className="ml-1 inline-block h-2 w-2 rounded-full bg-emerald-400 align-middle" />
              )}
            </button>
          </div>
        </div>
      </header>

      {showSettings && (
        <SettingsModal settings={settings} onClose={() => setShowSettings(false)} onSave={saveSettings} />
      )}

      <main className="mx-auto grid max-w-6xl gap-7 px-6 py-8 lg:grid-cols-2">
        {/* 왼쪽 */}
        <section className="space-y-6">
          {mode === "local" ? (
            <>
              <Card title="1. 음원 / 가사" step="①">
                <Dropzone
                  label="음원 파일"
                  hint="mp3 · wav · flac 드래그 또는 클릭"
                  accept="audio/*"
                  icon="🎵"
                  files={audio ? [audio] : []}
                  onFiles={(fs) => setAudio(fs[0] ?? null)}
                />
                {audio && <audio controls src={audioUrl} className="w-full" />}
                <Field label="가사 (텍스트)">
                  <textarea
                    value={lyricsText}
                    onChange={(e) => setLyricsText(e.target.value)}
                    placeholder="한 줄에 한 가사씩 — 곡 길이에 맞춰 자동 분배됩니다."
                    rows={4}
                    className={`${inputCls} resize-y`}
                  />
                </Field>
                <Dropzone
                  label="또는 가사 파일 (.lrc / .txt)"
                  hint=".lrc 면 정확한 싱크"
                  accept=".lrc,.txt"
                  icon="📝"
                  files={lyricsFile ? [lyricsFile] : []}
                  onFiles={(fs) => setLyricsFile(fs[0] ?? null)}
                />
                <Toggle checked={align} onChange={setAlign} label="AI 자동 가사 정렬 (백엔드 stable-ts 필요)" />
              </Card>

              <Card title="2. 배경 / 비주얼" step="②">
                <Dropzone
                  label="배경 이미지 (여러 장 = 크로스페이드)"
                  hint="jpg · png · webp"
                  accept="image/*"
                  icon="🖼️"
                  multiple
                  files={bgFiles}
                  onFiles={setBgFiles}
                />
                {bgUrls.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {bgUrls.map((u, i) => (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img key={i} src={u} alt="" className="h-16 w-24 rounded-md object-cover ring-1 ring-white/10" />
                    ))}
                  </div>
                )}
                <Field label="비주얼라이저">
                  <select value={viz} onChange={(e) => setViz(e.target.value)} className={inputCls}>
                    <option value="waves">파형 (waves)</option>
                    <option value="cqt">막대 스펙트럼 (cqt)</option>
                    <option value="spectrum">스펙트럼 (spectrum)</option>
                    <option value="none">없음</option>
                  </select>
                </Field>
                <Toggle checked={kenburns} onChange={setKenburns} label="배경 켄 번스(줌·팬) 효과" />
              </Card>

              <Card title="3. 포맷 / 메타" step="③">
                <Toggle checked={shorts} onChange={setShorts} label="쇼츠 세로형 (9:16, 1080×1920)" />
                <div className="grid grid-cols-2 gap-3">
                  <Field label="클립 시작 (mm:ss)">
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

              <button
                onClick={generate}
                disabled={submitting || busy}
                className="w-full rounded-xl bg-gradient-to-r from-indigo-500 to-fuchsia-500 px-4 py-3.5 font-semibold text-white shadow-lg shadow-indigo-500/20 transition hover:brightness-110 disabled:opacity-50"
              >
                {busy ? "렌더링 중…" : "🎬 뮤직비디오 생성"}
              </button>
            </>
          ) : (
            <Card title="AI 편집 ✨" step="🤖">
              <p className="text-xs text-neutral-400">
                먼저 <b>로컬 생성</b>으로 기본 영상을 만든 뒤, 자연어로 수정을 요청하세요.
                {!job && <span className="text-amber-300"> (편집할 프로젝트 없음)</span>}
              </p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => setChatInput(s)} className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-neutral-300 hover:bg-white/10">
                    {s}
                  </button>
                ))}
              </div>
              <div className="h-72 space-y-3 overflow-y-auto rounded-xl bg-black/30 p-3 ring-1 ring-white/10">
                {messages.length === 0 && <p className="text-xs text-neutral-500">예: &ldquo;쇼츠로 만들어줘&rdquo;, &ldquo;스펙트럼으로 바꿔줘&rdquo;</p>}
                {messages.map((m, i) => (
                  <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
                    <span className={`inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm ${m.role === "user" ? "bg-indigo-500/80 text-white" : "bg-white/10"}`}>
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
                <button onClick={sendAgent} disabled={agentBusy} className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50">
                  보내기
                </button>
              </div>
            </Card>
          )}
        </section>

        {/* 오른쪽 */}
        <section className="space-y-6 lg:sticky lg:top-24 lg:self-start">
          <Card title="결과 미리보기">
            {!job && (
              <div className="grid h-56 place-items-center rounded-xl border border-dashed border-white/10 text-sm text-neutral-500">
                생성하면 여기에 영상이 표시됩니다 🎥
              </div>
            )}
            {job && busy && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm text-neutral-300">
                  <Spinner /> {job.status === "queued" ? "대기 중…" : "렌더링 중…"}
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                  <div className="h-full w-1/3 animate-[loading_1.2s_ease-in-out_infinite] rounded-full bg-gradient-to-r from-indigo-400 to-fuchsia-400" />
                </div>
              </div>
            )}
            {job?.status === "error" && (
              <div className="space-y-2">
                <p className="text-sm text-red-400">렌더 실패: {job.error}</p>
                {job.log && <pre className="max-h-48 overflow-auto rounded-lg bg-black/40 p-3 text-xs whitespace-pre-wrap text-neutral-400">{job.log}</pre>}
              </div>
            )}
            {job?.status === "done" && job.video && (
              <div className="space-y-3">
                {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                <video src={`${API}/api/jobs/${job.id}/video`} controls className="mx-auto max-h-[68vh] w-full rounded-xl bg-black" />
                <div className="flex flex-wrap gap-2 text-sm">
                  <a href={`${API}/api/jobs/${job.id}/video`} download className="rounded-lg bg-white/10 px-3 py-2 hover:bg-white/20">⬇ 영상</a>
                  {job.thumb && <a href={`${API}/api/jobs/${job.id}/thumb`} download className="rounded-lg bg-white/10 px-3 py-2 hover:bg-white/20">⬇ 썸네일</a>}
                  <button onClick={() => setMode("ai")} className="rounded-lg bg-indigo-500/80 px-3 py-2 text-white hover:bg-indigo-500">✨ AI로 수정</button>
                </div>
              </div>
            )}
          </Card>

          <Card title="최근 작업">
            {recent.length === 0 ? (
              <p className="text-xs text-neutral-500">아직 없음</p>
            ) : (
              <div className="grid grid-cols-3 gap-2">
                {recent.slice(0, 9).map((r) => (
                  <button
                    key={r.id}
                    onClick={() => openJob(r.id)}
                    title={r.title}
                    className="group relative overflow-hidden rounded-lg ring-1 ring-white/10 hover:ring-indigo-400"
                  >
                    {r.thumb ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={`${API}/api/jobs/${r.id}/thumb`} alt="" className="aspect-video w-full object-cover" />
                    ) : (
                      <div className="grid aspect-video place-items-center bg-white/5 text-[10px] text-neutral-400">
                        {r.status === "error" ? "실패" : r.status}
                      </div>
                    )}
                    <span className="absolute inset-x-0 bottom-0 truncate bg-black/60 px-1 py-0.5 text-[10px] text-neutral-200">
                      {r.shorts ? "📱 " : ""}{r.title || r.id}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </Card>
        </section>
      </main>

      <style>{`@keyframes loading{0%{transform:translateX(-120%)}100%{transform:translateX(320%)}}`}</style>
    </div>
  );
}

const inputCls =
  "w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none transition focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400/40";

function Card({ title, step, children }: { title: string; step?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-4 rounded-2xl border border-white/10 bg-white/[0.04] p-5 shadow-xl shadow-black/20 backdrop-blur">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-neutral-200">
        {step && <span className="text-neutral-500">{step}</span>}
        {title}
      </h2>
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

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button onClick={() => onChange(!checked)} className="flex w-full items-center gap-3 text-left text-sm text-neutral-300">
      <span className={`relative h-5 w-9 shrink-0 rounded-full transition ${checked ? "bg-indigo-500" : "bg-white/15"}`}>
        <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${checked ? "left-[18px]" : "left-0.5"}`} />
      </span>
      {label}
    </button>
  );
}

function Spinner() {
  return <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-indigo-400" />;
}

function Dropzone({
  label,
  hint,
  accept,
  icon,
  multiple = false,
  files,
  onFiles,
}: {
  label: string;
  hint: string;
  accept: string;
  icon: string;
  multiple?: boolean;
  files: File[];
  onFiles: (f: File[]) => void;
}) {
  const [over, setOver] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className="space-y-1.5">
      <span className="text-xs font-medium text-neutral-400">{label}</span>
      <div
        onClick={() => ref.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const fs = Array.from(e.dataTransfer.files);
          if (fs.length) onFiles(multiple ? fs : [fs[0]]);
        }}
        className={`cursor-pointer rounded-xl border-2 border-dashed p-4 text-center transition ${
          over ? "border-indigo-400 bg-indigo-500/10" : "border-white/15 hover:border-white/30 hover:bg-white/5"
        }`}
      >
        <input
          ref={ref}
          type="file"
          accept={accept}
          multiple={multiple}
          className="hidden"
          onChange={(e) => onFiles(Array.from(e.target.files ?? []))}
        />
        {files.length === 0 ? (
          <p className="text-sm text-neutral-400">
            <span className="mr-1">{icon}</span>
            <span className="text-neutral-300">{hint}</span>
          </p>
        ) : (
          <p className="truncate text-sm text-neutral-200">
            {icon} {files.length === 1 ? files[0].name : `${files.length}개 선택됨`}
          </p>
        )}
      </div>
    </div>
  );
}

function SettingsModal({
  settings,
  onClose,
  onSave,
}: {
  settings: Settings | null;
  onClose: () => void;
  onSave: (patch: Record<string, string>) => Promise<void>;
}) {
  const [llmProvider, setLlmProvider] = useState(settings?.llm_provider ?? "claude");
  const [llmModel, setLlmModel] = useState(settings?.llm_model ?? "claude-sonnet-4-6");
  const [llmKey, setLlmKey] = useState("");
  const [videoProvider, setVideoProvider] = useState(settings?.video_provider ?? "kaiber");
  const [videoKey, setVideoKey] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    const patch: Record<string, string> = {
      llm_provider: llmProvider,
      llm_model: llmModel,
      video_provider: videoProvider,
    };
    if (llmKey.trim()) patch.llm_api_key = llmKey.trim();
    if (videoKey.trim()) patch.video_api_key = videoKey.trim();
    await onSave(patch);
    setLlmKey("");
    setVideoKey("");
    setSaving(false);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-lg space-y-5 rounded-2xl border border-white/10 bg-neutral-900 p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">⚙️ API 키 설정 (BYOK)</h2>
          <button onClick={onClose} className="text-neutral-400 hover:text-neutral-200">✕</button>
        </div>
        <p className="text-xs text-neutral-400">키는 백엔드 로컬에만 저장되고 화면엔 다시 표시되지 않습니다(설정 여부만 표시). provider는 언제든 교체 가능.</p>

        <div className="space-y-3 rounded-xl border border-white/10 bg-white/5 p-4">
          <h3 className="text-sm font-medium">AI 편집 (LLM)</h3>
          <Field label="Provider">
            <select value={llmProvider} onChange={(e) => setLlmProvider(e.target.value)} className={inputCls}>
              <option value="claude">Claude (Anthropic)</option>
            </select>
          </Field>
          <Field label="모델">
            <input value={llmModel} onChange={(e) => setLlmModel(e.target.value)} className={inputCls} />
          </Field>
          <Field label={`API 키 ${settings?.llm_key_set ? "(설정됨 ✓ — 바꿀 때만 입력)" : "(미설정)"}`}>
            <input type="password" value={llmKey} onChange={(e) => setLlmKey(e.target.value)} placeholder="sk-ant-..." className={inputCls} />
          </Field>
        </div>

        <div className="space-y-3 rounded-xl border border-white/10 bg-white/5 p-4">
          <h3 className="text-sm font-medium">AI 영상 생성 (배경)</h3>
          <Field label="Provider">
            <select value={videoProvider} onChange={(e) => setVideoProvider(e.target.value)} className={inputCls}>
              <option value="kaiber">Kaiber</option>
              <option value="higgsfield">Higgsfield</option>
            </select>
          </Field>
          <Field label={`API 키 ${settings?.video_key_set ? "(설정됨 ✓)" : "(미설정)"}`}>
            <input type="password" value={videoKey} onChange={(e) => setVideoKey(e.target.value)} placeholder="키 입력" className={inputCls} />
          </Field>
        </div>

        <div className="flex justify-end">
          <button onClick={save} disabled={saving} className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50">
            {saving ? "저장 중…" : "저장"}
          </button>
        </div>
      </div>
    </div>
  );
}
