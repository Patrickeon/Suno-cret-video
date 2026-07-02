"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Card, Dropzone, Field, Spinner, Toggle } from "./components/ui";
import { SettingsModal } from "./components/SettingsModal";
import { HelpModal } from "./components/HelpModal";
import { PublishPanel } from "./components/PublishPanel";
import { LyricSyncModal } from "./components/LyricSyncModal";
import {
  API,
  BG_PRESETS,
  inputCls,
  Job,
  JobSummary,
  ChatMsg,
  PRESETS,
  Settings,
  SUGGESTIONS,
  Toast,
} from "./lib/studio";

let toastSeq = 0;

export default function Home() {
  const [mode, setMode] = useState<"local" | "ai">("local");

  // 입력
  const [audio, setAudio] = useState<File | null>(null);
  const [lyricsText, setLyricsText] = useState("");
  const [lyricsFile, setLyricsFile] = useState<File | null>(null);
  const [bgFiles, setBgFiles] = useState<File[]>([]);
  const [bgPick, setBgPick] = useState("");
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [introClip, setIntroClip] = useState<File | null>(null);
  const [outroClip, setOutroClip] = useState<File | null>(null);
  const [albumFiles, setAlbumFiles] = useState<File[]>([]);
  const [albumBusy, setAlbumBusy] = useState(false);
  const [translateBusy, setTranslateBusy] = useState(false);
  const [translateTarget, setTranslateTarget] = useState("영어");

  // 옵션
  const [viz, setViz] = useState("waves");
  const [shorts, setShorts] = useState(false);
  const [clipStart, setClipStart] = useState("");
  const [clipLen, setClipLen] = useState(30);
  const [kenburns, setKenburns] = useState(true);
  const [bgColor, setBgColor] = useState("0x0a0a14");
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [watermark, setWatermark] = useState("");
  const [align, setAlign] = useState(false);

  // 자막 스타일
  const [subColor, setSubColor] = useState("FFFFFF");
  const [subSize, setSubSize] = useState(1.0);
  const [subPos, setSubPos] = useState("bottom");
  const [subGlow, setSubGlow] = useState(false);
  const [font, setFont] = useState("");
  const [fonts, setFonts] = useState<{ label: string; family: string }[]>([]);
  const [introCard, setIntroCard] = useState(false);
  const [interludeNote, setInterludeNote] = useState(false);
  const [autoRetry, setAutoRetry] = useState(true);
  const [audioDur, setAudioDur] = useState(0);

  // 히스토리 검색/필터
  const [recentSearch, setRecentSearch] = useState("");
  const [recentFilter, setRecentFilter] = useState("all");

  // 품질 / 마감 (유튜브)
  const [res, setRes] = useState("1080");
  const [fps, setFps] = useState(30);
  const [normalize, setNormalize] = useState(true);
  const [master, setMaster] = useState(false);
  const [karaoke, setKaraoke] = useState(false);
  const [fadeIn, setFadeIn] = useState(0);
  const [fadeOut, setFadeOut] = useState(0);
  const [vignette, setVignette] = useState(false);
  const [filmGrain, setFilmGrain] = useState(false);
  const [bgPulse, setBgPulse] = useState(false);

  // 잡 / 결과
  const [job, setJob] = useState<Job | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [recent, setRecent] = useState<JobSummary[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // AI 채팅
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);

  // AI 배경 영상
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiVideoBusy, setAiVideoBusy] = useState(false);

  // 설정 / 도움말 / 테마 / 토스트
  const [showSettings, setShowSettings] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showSync, setShowSync] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  // 프로젝트 프리셋 (스타일/품질 조합, localStorage)
  const [presets, setPresets] = useState<Record<string, Record<string, unknown>>>({});
  useEffect(() => {
    try {
      setPresets(JSON.parse(localStorage.getItem("mv_presets") || "{}"));
    } catch {
      /* 무시 */
    }
  }, []);

  // 사전 스크립트가 적용한 테마를 상태에 동기화 (마운트 시 1회)
  useEffect(() => {
    setTheme(document.documentElement.classList.contains("light") ? "light" : "dark");
  }, []);

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.classList.toggle("light", next === "light");
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* localStorage 불가 환경 무시 */
    }
  }

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
    fetch(`${API}/api/fonts`).then((r) => r.json()).then((d) => setFonts(d.fonts ?? [])).catch(() => {});
    refreshRecent();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refreshRecent]);

  // 미리보기 URL
  const audioUrl = useMemo(() => (audio ? URL.createObjectURL(audio) : ""), [audio]);
  const bgUrls = useMemo(() => bgFiles.map((f) => URL.createObjectURL(f)), [bgFiles]);
  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl); }, [audioUrl]);
  // 오디오 길이 → 예상 렌더 시간 계산용
  useEffect(() => {
    if (!audioUrl) { setAudioDur(0); return; }
    const a = new Audio(audioUrl);
    const on = () => setAudioDur(a.duration || 0);
    a.addEventListener("loadedmetadata", on);
    return () => a.removeEventListener("loadedmetadata", on);
  }, [audioUrl]);
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

  function persistPresets(p: Record<string, Record<string, unknown>>) {
    setPresets(p);
    try {
      localStorage.setItem("mv_presets", JSON.stringify(p));
    } catch {
      /* 무시 */
    }
  }

  function savePreset() {
    const name = window.prompt("프리셋 이름을 입력하세요")?.trim();
    if (!name) return;
    const snap = {
      viz, shorts, kenburns, bgColor, watermark, align, res, fps,
      normalize, master, karaoke, fadeIn, fadeOut, vignette, filmGrain,
      subColor, subSize, subPos, clipLen,
    };
    persistPresets({ ...presets, [name]: snap });
    toast(`프리셋 '${name}' 저장됨`, "success");
  }

  function applyPreset(name: string) {
    const s = presets[name];
    if (!s) return;
    const b = (k: string, d: boolean) => (typeof s[k] === "boolean" ? (s[k] as boolean) : d);
    const str = (k: string, d: string) => (typeof s[k] === "string" ? (s[k] as string) : d);
    const num = (k: string, d: number) => (typeof s[k] === "number" ? (s[k] as number) : d);
    setViz(str("viz", "waves"));
    setShorts(b("shorts", false));
    setKenburns(b("kenburns", true));
    setBgColor(str("bgColor", "0x0a0a14"));
    setWatermark(str("watermark", ""));
    setAlign(b("align", false));
    setRes(str("res", "1080"));
    setFps(num("fps", 30));
    setNormalize(b("normalize", true));
    setMaster(b("master", false));
    setKaraoke(b("karaoke", false));
    setFadeIn(num("fadeIn", 0));
    setFadeOut(num("fadeOut", 0));
    setVignette(b("vignette", false));
    setFilmGrain(b("filmGrain", false));
    setSubColor(str("subColor", "FFFFFF"));
    setSubSize(num("subSize", 1));
    setSubPos(str("subPos", "bottom"));
    setClipLen(num("clipLen", 30));
    toast(`'${name}' 프리셋 적용`, "info");
  }

  function deletePreset(name: string) {
    const rest = { ...presets };
    delete rest[name];
    persistPresets(rest);
  }

  function poll(id: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`${API}/api/jobs/${id}`);
        if (!r.ok) return;
        const j: Job = await r.json();
        setJob(j);
        if (j.status === "done" || j.status === "error" || j.status === "cancelled") {
          if (pollRef.current) clearInterval(pollRef.current);
          refreshRecent();
          if (j.status === "done") toast("렌더 완료 ✓", "success");
          else if (j.status === "error") toast("렌더 실패", "error");
        }
      } catch {
        /* 일시 오류 무시 */
      }
    }, 1500);
  }

  async function generate(preview = false) {
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
      if (logoFile) fd.append("logo", logoFile);
      if (introClip) fd.append("intro_clip", introClip);
      if (outroClip) fd.append("outro_clip", outroClip);
      fd.append("preview", String(preview));
      fd.append("viz", viz);
      fd.append("shorts", String(shorts));
      fd.append("clip_start", clipStart);
      fd.append("clip_len", String(clipLen));
      fd.append("kenburns", String(kenburns));
      fd.append("bg_color", bgColor);
      fd.append("title", title);
      fd.append("artist", artist);
      fd.append("watermark", watermark);
      fd.append("align", align ? "auto" : "none");
      fd.append("res", res);
      fd.append("fps", String(fps));
      fd.append("normalize", String(normalize));
      fd.append("master", String(master));
      fd.append("karaoke", String(karaoke));
      fd.append("fade_in", String(fadeIn));
      fd.append("fade_out", String(fadeOut));
      fd.append("vignette", String(vignette));
      fd.append("film_grain", String(filmGrain));
      fd.append("bg_pulse", String(bgPulse));
      fd.append("sub_color", subColor);
      fd.append("sub_size", String(subSize));
      fd.append("sub_pos", subPos);
      fd.append("sub_glow", String(subGlow));
      fd.append("intro_card", String(introCard));
      fd.append("interlude_note", String(interludeNote));
      if (font) fd.append("font", font);
      fd.append("auto_retry", String(autoRetry));

      const r = await fetch(`${API}/api/render`, { method: "POST", body: fd });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `서버 오류 (${r.status})`);
      setJob({ id: data.job_id, status: "queued", progress: 0, error: null, log: "", video: false, thumb: false });
      poll(data.job_id);
      toast(preview ? "⚡ 미리보기 렌더 시작 (앞부분·저화질)" : "렌더를 시작했어요.", "info");
    } catch (e) {
      toast(e instanceof Error ? e.message : "요청 실패", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function albumGenerate() {
    if (!albumFiles.length) {
      toast("앨범에 넣을 음원들을 선택하세요.", "error");
      return;
    }
    setAlbumBusy(true);
    toast(`${albumFiles.length}곡 일괄 렌더를 큐에 넣는 중…`, "info");
    for (const f of albumFiles) {
      const fd = new FormData();
      fd.append("audio", f);
      bgFiles.forEach((b) => fd.append("bg", b));
      if (logoFile) fd.append("logo", logoFile);
      fd.append("viz", viz);
      fd.append("res", res);
      fd.append("fps", String(fps));
      fd.append("kenburns", String(kenburns));
      fd.append("bg_color", bgColor);
      fd.append("normalize", String(normalize));
      fd.append("master", String(master));
      fd.append("vignette", String(vignette));
      fd.append("film_grain", String(filmGrain));
      fd.append("bg_pulse", String(bgPulse));
      fd.append("watermark", watermark);
      fd.append("title", f.name.replace(/\.[^.]+$/, ""));
      try {
        await fetch(`${API}/api/render`, { method: "POST", body: fd });
      } catch {
        /* 개별 실패 무시 */
      }
    }
    refreshRecent();
    setAlbumBusy(false);
    toast("앨범 일괄 렌더가 시작됐어요. ‘최근 작업’에서 확인하세요.", "success");
  }

  async function translateLyrics() {
    if (!lyricsText.trim()) {
      toast("번역할 가사를 먼저 입력하세요.", "error");
      return;
    }
    setTranslateBusy(true);
    try {
      const r = await fetch(`${API}/api/translate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: lyricsText, target: translateTarget, bilingual: true }),
      });
      const data = await r.json();
      if (!r.ok || data.error) throw new Error(data.error || `오류 (${r.status})`);
      setLyricsText(data.text);
      toast("이중 자막(원문+번역)으로 바꿨어요. ‘||’ 는 줄바꿈으로 렌더됩니다.", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "번역 실패", "error");
    } finally {
      setTranslateBusy(false);
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
      setJob({ id: data.job_id, status: "queued", progress: 0, error: null, log: "", video: false, thumb: false });
      poll(data.job_id);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", text: "⚠ " + (e instanceof Error ? e.message : "에이전트 오류") }]);
    } finally {
      setAgentBusy(false);
    }
  }

  async function generateAiVideo() {
    const prompt = aiPrompt.trim();
    if (!prompt) return;
    if (!job || job.status !== "done") {
      toast("먼저 '로컬 생성'으로 기본 영상을 만든 뒤 AI 배경을 생성하세요.", "error");
      return;
    }
    setAiVideoBusy(true);
    try {
      const r = await fetch(`${API}/api/ai-video`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: job.id, prompt }),
      });
      const data = await r.json();
      if (!r.ok || data.error) throw new Error(data.error || `오류 (${r.status})`);
      setJob({ id: data.job_id, status: "queued", progress: 0, error: null, log: "", video: false, thumb: false });
      poll(data.job_id);
      toast("AI 배경 영상 생성 + 재렌더를 시작했어요. 수십 초~수 분 걸릴 수 있어요.", "info");
    } catch (e) {
      toast(e instanceof Error ? e.message : "AI 영상 요청 실패", "error");
    } finally {
      setAiVideoBusy(false);
    }
  }

  async function cancelJob(id: string) {
    try {
      await fetch(`${API}/api/jobs/${id}/cancel`, { method: "POST" });
      toast("취소를 요청했어요.", "info");
    } catch {
      toast("취소 실패", "error");
    }
  }

  async function deleteJob(id: string) {
    try {
      const r = await fetch(`${API}/api/jobs/${id}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      if (job?.id === id) {
        if (pollRef.current) clearInterval(pollRef.current);
        setJob(null);
      }
      refreshRecent();
      toast("삭제했어요.", "info");
    } catch {
      toast("삭제 실패", "error");
    }
  }

  async function pickBuiltinBg(id: string) {
    try {
      const r = await fetch(`/bg/${id}.jpg`);
      const blob = await r.blob();
      setBgFiles([new File([blob], `${id}.jpg`, { type: "image/jpeg" })]);
      setBgPick(id);
      toast("기본 배경을 적용했어요.", "info");
    } catch {
      toast("배경 로드 실패", "error");
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

  // 예상 렌더 시간 (거친 추정: 곡 길이 × 해상도/옵션 배수)
  const etaText = useMemo(() => {
    if (!audioDur) return "";
    let f = 0.55; // 1080p medium 기준 realtime 배수
    if (res === "1440") f *= 2.0;
    else if (res === "2160") f *= 4.0;
    if (fps === 60) f *= 1.6;
    if (master) f *= 1.3;
    const sec = Math.max(5, Math.round(audioDur * f));
    return sec >= 60 ? `~${Math.round(sec / 60)}분` : `~${sec}초`;
  }, [audioDur, res, fps, master]);

  function exportPresets() {
    const blob = new Blob([JSON.stringify(presets, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "mv-presets.json"; a.click();
    URL.revokeObjectURL(url);
  }

  function importPresets(file: File) {
    file.text().then((txt) => {
      try {
        const obj = JSON.parse(txt);
        if (obj && typeof obj === "object") {
          persistPresets({ ...presets, ...obj });
          toast("프리셋을 가져왔어요.", "success");
        }
      } catch {
        toast("프리셋 파일이 올바르지 않습니다.", "error");
      }
    });
  }

  const filteredRecent = useMemo(
    () => recent.filter((r) =>
      (recentFilter === "all" || r.status === recentFilter) &&
      (!recentSearch.trim() || (r.title || "").toLowerCase().includes(recentSearch.trim().toLowerCase()))
    ),
    [recent, recentFilter, recentSearch],
  );

  const jobStats = useMemo(() => {
    const s = { running: 0, queued: 0, done: 0, error: 0 };
    recent.forEach((r) => {
      if (r.status === "running") s.running++;
      else if (r.status === "queued") s.queued++;
      else if (r.status === "done") s.done++;
      else if (r.status === "error") s.error++;
    });
    return s;
  }, [recent]);

  const busy = job?.status === "queued" || job?.status === "running";

  return (
    <div className="app-shell min-h-full">
      {/* 토스트 */}
      <div className="fixed right-4 top-4 z-[60] flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`rounded-lg px-4 py-2.5 text-sm shadow-lg backdrop-blur ${
              t.kind === "success"
                ? "bg-emerald-500 text-white"
                : t.kind === "error"
                ? "bg-red-500 text-white"
                : "border border-[var(--border)] bg-[var(--surface)] text-[var(--text)]"
            }`}
          >
            {t.text}
          </div>
        ))}
      </div>

      <header className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--surface-2)] px-4 py-3 backdrop-blur-md sm:px-6 sm:py-3.5">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-lg shadow-lg">
              🎬
            </span>
            <div>
              <h1 className="text-base font-semibold leading-tight tracking-tight">Suno MV Studio</h1>
              <p className="hidden text-[11px] text-[var(--text-dim)] sm:block">음원 + 가사 → AI 뮤직비디오</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex rounded-lg bg-[var(--surface-2)] p-1 text-sm ring-1 ring-[var(--border)]">
              <button
                onClick={() => setMode("local")}
                className={`rounded-md px-3 py-1.5 transition ${mode === "local" ? "bg-[var(--surface-3)] font-medium" : "text-[var(--text-dim)] hover:text-[var(--text)]"}`}
              >
                로컬 생성
              </button>
              <button
                onClick={() => setMode("ai")}
                className={`rounded-md px-3 py-1.5 transition ${mode === "ai" ? "bg-[var(--surface-3)] font-medium" : "text-[var(--text-dim)] hover:text-[var(--text)]"}`}
              >
                AI 편집 ✨
              </button>
            </div>
            <button
              onClick={() => setShowHelp(true)}
              title="사용법"
              className="rounded-lg bg-[var(--surface-2)] px-3 py-1.5 text-sm text-[var(--text-dim)] ring-1 ring-[var(--border)] hover:bg-[var(--surface-3)]"
            >
              ❓
            </button>
            <button
              onClick={toggleTheme}
              title={theme === "dark" ? "라이트 모드로" : "다크 모드로"}
              className="rounded-lg bg-[var(--surface-2)] px-3 py-1.5 text-sm text-[var(--text-dim)] ring-1 ring-[var(--border)] hover:bg-[var(--surface-3)]"
            >
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
            <button
              onClick={() => setShowSettings(true)}
              title="API 키 설정"
              className="rounded-lg bg-[var(--surface-2)] px-3 py-1.5 text-sm text-[var(--text-dim)] ring-1 ring-[var(--border)] hover:bg-[var(--surface-3)]"
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
      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}
      {showSync && audio && (
        <LyricSyncModal
          audio={audio}
          lyrics={lyricsText}
          onClose={() => setShowSync(false)}
          onApply={(lrc) => {
            setLyricsFile(new File([lrc], "synced.lrc", { type: "text/plain" }));
            setLyricsText("");
            setShowSync(false);
            toast("싱크된 LRC를 가사 파일로 적용했어요.", "success");
          }}
        />
      )}

      <main className="mx-auto grid max-w-6xl gap-6 px-4 py-6 sm:px-6 sm:py-8 lg:grid-cols-2">
        {/* 왼쪽 */}
        <section className="space-y-6">
          {mode === "local" ? (
            <>
              <div className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3">
                <span className="text-xs font-medium text-[var(--text-dim)]">프리셋</span>
                {Object.keys(presets).length === 0 && (
                  <span className="text-[11px] text-[var(--text-faint)]">저장된 프리셋 없음</span>
                )}
                {Object.keys(presets).map((n) => (
                  <span key={n} className="flex items-center gap-1 rounded-full bg-[var(--surface-2)] px-2 py-1 text-xs ring-1 ring-[var(--border)]">
                    <button onClick={() => applyPreset(n)} className="hover:text-white">{n}</button>
                    <button onClick={() => deletePreset(n)} title="삭제" className="text-[var(--text-faint)] hover:text-red-400">✕</button>
                  </span>
                ))}
                <div className="ml-auto flex items-center gap-1.5">
                  <button onClick={savePreset} className="rounded-lg bg-[var(--surface-2)] px-3 py-1 text-xs text-[var(--text)] hover:bg-[var(--surface-3)]">
                    ＋ 저장
                  </button>
                  {Object.keys(presets).length > 0 && (
                    <button onClick={exportPresets} title="프리셋 내보내기(JSON)" className="rounded-lg bg-[var(--surface-2)] px-2 py-1 text-xs text-[var(--text-dim)] hover:bg-[var(--surface-3)]">
                      ⬇
                    </button>
                  )}
                  <label title="프리셋 가져오기(JSON)" className="cursor-pointer rounded-lg bg-[var(--surface-2)] px-2 py-1 text-xs text-[var(--text-dim)] hover:bg-[var(--surface-3)]">
                    ⬆
                    <input
                      type="file"
                      accept="application/json,.json"
                      className="hidden"
                      onChange={(e) => { const f = e.target.files?.[0]; if (f) importPresets(f); e.target.value = ""; }}
                    />
                  </label>
                </div>
              </div>

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
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[var(--text-faint)]">🌏 번역</span>
                  <select
                    value={translateTarget}
                    onChange={(e) => setTranslateTarget(e.target.value)}
                    className={`${inputCls} w-28`}
                  >
                    <option value="영어">영어</option>
                    <option value="일본어">일본어</option>
                    <option value="중국어">중국어</option>
                    <option value="스페인어">스페인어</option>
                  </select>
                  <button
                    onClick={translateLyrics}
                    disabled={translateBusy}
                    className="rounded-lg bg-[var(--surface-2)] px-3 py-2 text-xs text-[var(--text)] hover:bg-[var(--surface-3)] disabled:opacity-50"
                  >
                    {translateBusy ? "번역 중…" : "이중 자막 만들기"}
                  </button>
                  <button
                    onClick={() => {
                      if (!audio) return toast("음원을 먼저 올리세요.", "error");
                      if (!lyricsText.trim()) return toast("가사를 먼저 입력하세요.", "error");
                      setShowSync(true);
                    }}
                    className="rounded-lg bg-[var(--surface-2)] px-3 py-2 text-xs text-[var(--text)] hover:bg-[var(--surface-3)]"
                  >
                    🎯 싱크 맞추기
                  </button>
                </div>
                <Dropzone
                  label="또는 가사 파일 (.lrc / .txt)"
                  hint=".lrc 면 정확한 싱크"
                  accept=".lrc,.txt"
                  icon="📝"
                  files={lyricsFile ? [lyricsFile] : []}
                  onFiles={(fs) => setLyricsFile(fs[0] ?? null)}
                />
                <Toggle checked={align} onChange={setAlign} label="AI 자동 가사 정렬 (백엔드 stable-ts 필요)" />
                <Toggle checked={karaoke} onChange={setKaraoke} label="🎤 카라오케 색채움 (글자 스윕)" />
                <div className="grid grid-cols-3 gap-3">
                  <Field label="자막 색">
                    <input
                      type="color"
                      value={`#${subColor}`}
                      onChange={(e) => setSubColor(e.target.value.slice(1).toUpperCase())}
                      className="h-9 w-full cursor-pointer rounded-lg bg-[var(--surface-2)] ring-1 ring-[var(--border)]"
                    />
                  </Field>
                  <Field label="자막 크기">
                    <select value={subSize} onChange={(e) => setSubSize(Number(e.target.value))} className={inputCls}>
                      <option value={0.85}>작게</option>
                      <option value={1}>보통</option>
                      <option value={1.2}>크게</option>
                      <option value={1.4}>아주 크게</option>
                    </select>
                  </Field>
                  <Field label="자막 위치">
                    <select value={subPos} onChange={(e) => setSubPos(e.target.value)} className={inputCls}>
                      <option value="bottom">하단</option>
                      <option value="middle">중앙</option>
                      <option value="top">상단</option>
                    </select>
                  </Field>
                </div>
                <Field label="자막 폰트">
                  <select value={font} onChange={(e) => setFont(e.target.value)} className={inputCls}>
                    <option value="">기본 (맑은 고딕)</option>
                    {fonts.map((f) => (
                      <option key={f.family} value={f.family}>{f.label}</option>
                    ))}
                  </select>
                </Field>
                <Toggle checked={subGlow} onChange={setSubGlow} label="✨ 자막 글로우 (발광)" />
              </Card>

              <Card title="2. 배경 / 비주얼" step="②">
                <div className="space-y-1.5">
                  <span className="text-xs font-medium text-[var(--text-dim)]">빠른 프리셋</span>
                  <div className="flex flex-wrap gap-2">
                    {PRESETS.map((p) => {
                      const active = viz === p.viz && kenburns === p.kenburns && bgColor === p.bg;
                      return (
                        <button
                          key={p.name}
                          onClick={() => { setViz(p.viz); setKenburns(p.kenburns); setBgColor(p.bg); }}
                          className={`rounded-full border px-3 py-1 text-xs transition ${
                            active
                              ? "border-indigo-400 bg-indigo-500/20 text-white"
                              : "border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-dim)] hover:bg-[var(--surface-3)]"
                          }`}
                        >
                          {p.emoji} {p.name}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <span className="text-xs font-medium text-[var(--text-dim)]">기본 배경 (그라데이션)</span>
                  <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                    {BG_PRESETS.map((b) => (
                      <button
                        key={b.id}
                        onClick={() => pickBuiltinBg(b.id)}
                        title={b.label}
                        className={`overflow-hidden rounded-lg ring-1 transition ${
                          bgPick === b.id ? "ring-2 ring-indigo-400" : "ring-[var(--border)] hover:ring-indigo-300"
                        }`}
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={`/bg/${b.id}.jpg`} alt={b.label} className="aspect-video w-full object-cover" />
                      </button>
                    ))}
                  </div>
                </div>
                <Dropzone
                  label="또는 직접 배경 이미지 (여러 장 = 크로스페이드)"
                  hint="jpg · png · webp"
                  accept="image/*"
                  icon="🖼️"
                  multiple
                  files={bgFiles}
                  onFiles={(fs) => { setBgFiles(fs); setBgPick(""); }}
                />
                {bgUrls.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {bgUrls.map((u, i) => (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img key={i} src={u} alt="" className="h-16 w-24 rounded-md object-cover ring-1 ring-[var(--border)]" />
                    ))}
                  </div>
                )}
                <Field label="비주얼라이저">
                  <select value={viz} onChange={(e) => setViz(e.target.value)} className={inputCls}>
                    <option value="waves">파형 (waves)</option>
                    <option value="bars">컬러 막대 (bars)</option>
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
                <Dropzone
                  label="로고 (우하단 · 워터마크보다 우선 · 채널 브랜딩)"
                  hint="png 권장 (투명 배경)"
                  accept="image/*"
                  icon="🏷️"
                  files={logoFile ? [logoFile] : []}
                  onFiles={(fs) => setLogoFile(fs[0] ?? null)}
                />
                <div className="grid grid-cols-2 gap-3">
                  <Dropzone
                    label="인트로 클립 (앞에 붙임)"
                    hint="mp4 · mov"
                    accept="video/*"
                    icon="🎬"
                    files={introClip ? [introClip] : []}
                    onFiles={(fs) => setIntroClip(fs[0] ?? null)}
                  />
                  <Dropzone
                    label="아웃트로 클립 (끝에 붙임)"
                    hint="구독 유도 등"
                    accept="video/*"
                    icon="🎬"
                    files={outroClip ? [outroClip] : []}
                    onFiles={(fs) => setOutroClip(fs[0] ?? null)}
                  />
                </div>
              </Card>

              <Card title="4. 품질 / 마감 (유튜브)" step="④">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="해상도">
                    <select value={res} onChange={(e) => setRes(e.target.value)} className={inputCls}>
                      <option value="1080">1080p (FHD)</option>
                      <option value="1440">1440p (QHD · 권장)</option>
                      <option value="2160">2160p (4K)</option>
                    </select>
                  </Field>
                  <Field label="프레임레이트">
                    <select value={fps} onChange={(e) => setFps(Number(e.target.value))} className={inputCls}>
                      <option value={30}>30 fps</option>
                      <option value={60}>60 fps</option>
                      <option value={24}>24 fps (영화)</option>
                    </select>
                  </Field>
                </div>
                <p className="text-[11px] text-[var(--text-faint)]">
                  1440p 이상으로 올리면 유튜브가 더 좋은 코덱(VP9)을 적용해 선명해집니다.
                </p>
                <Toggle checked={normalize} onChange={setNormalize} label="라우드니스 정규화 (-14 LUFS, 유튜브 표준)" />
                <Toggle checked={master} onChange={setMaster} label="🎚 정밀 마스터링 (2-pass + 리미터, 느리지만 정확)" />
                {master && <p className="text-[11px] text-[var(--text-faint)]">측정 패스가 추가돼 렌더가 조금 더 걸립니다.</p>}
                <div className="grid grid-cols-2 gap-3">
                  <Field label="페이드 인 (초)">
                    <input type="number" min={0} step={0.5} value={fadeIn} onChange={(e) => setFadeIn(Number(e.target.value))} className={inputCls} />
                  </Field>
                  <Field label="페이드 아웃 (초)">
                    <input type="number" min={0} step={0.5} value={fadeOut} onChange={(e) => setFadeOut(Number(e.target.value))} className={inputCls} />
                  </Field>
                </div>
                <div className="flex flex-wrap gap-x-6 gap-y-2">
                  <Toggle checked={vignette} onChange={setVignette} label="비네트" />
                  <Toggle checked={filmGrain} onChange={setFilmGrain} label="필름 그레인" />
                </div>
                <Toggle checked={bgPulse} onChange={setBgPulse} label="🔊 오디오 반응 배경 (음량에 밝기 펄스)" />
                <Toggle checked={introCard} onChange={setIntroCard} label="🎬 인트로 타이틀 카드 (제목/아티스트 페이드인)" />
                <Toggle checked={interludeNote} onChange={setInterludeNote} label="🎵 간주 구간에 ♪ 표시" />
                <Toggle checked={autoRetry} onChange={setAutoRetry} label="🔁 실패 시 자동 재시도 (1회)" />
              </Card>

              <div className="flex gap-2">
                <button
                  onClick={() => generate(true)}
                  disabled={submitting || busy}
                  className="shrink-0 rounded-xl bg-[var(--surface-2)] px-4 py-3.5 text-sm font-medium text-[var(--text)] ring-1 ring-[var(--border)] transition hover:bg-[var(--surface-3)] disabled:opacity-50"
                  title="앞부분만 저화질로 빠르게 확인"
                >
                  ⚡ 미리보기
                </button>
                <button
                  onClick={() => generate(false)}
                  disabled={submitting || busy}
                  className="w-full rounded-xl bg-gradient-to-r from-indigo-500 to-fuchsia-500 px-4 py-3.5 font-semibold text-white shadow-lg shadow-indigo-500/20 transition hover:brightness-110 disabled:opacity-50"
                >
                  {busy ? "렌더링 중…" : "🎬 뮤직비디오 생성"}
                </button>
              </div>
              {etaText && !busy && (
                <p className="text-center text-[11px] text-[var(--text-faint)]">
                  예상 렌더 시간 {etaText} <span className="opacity-70">(해상도·옵션 기준 대략치)</span>
                </p>
              )}

              <Card title="🎵 앨범 일괄 (여러 곡, 같은 스타일)" step="＋">
                <p className="text-[11px] text-[var(--text-faint)]">
                  현재 배경·비주얼·품질·워터마크·로고 설정을 그대로 써서 여러 곡을 한 번에 렌더합니다.
                  (제목은 파일명, 가사는 생략)
                </p>
                <Dropzone
                  label="음원 여러 개"
                  hint="mp3 · wav · flac 여러 개 선택"
                  accept="audio/*"
                  icon="🎶"
                  multiple
                  files={albumFiles}
                  onFiles={setAlbumFiles}
                />
                <button
                  onClick={albumGenerate}
                  disabled={albumBusy || albumFiles.length === 0}
                  className="w-full rounded-xl bg-[var(--surface-2)] px-4 py-3 text-sm font-medium text-[var(--text)] ring-1 ring-[var(--border)] transition hover:bg-[var(--surface-3)] disabled:opacity-50"
                >
                  {albumBusy ? "큐에 넣는 중…" : `📀 ${albumFiles.length || ""}곡 일괄 생성`}
                </button>
              </Card>
            </>
          ) : (
            <Card title="AI 편집 ✨" step="🤖">
              <p className="text-xs text-[var(--text-dim)]">
                먼저 <b>로컬 생성</b>으로 기본 영상을 만든 뒤, 자연어로 수정을 요청하세요.
                {!job && <span className="text-amber-300"> (편집할 프로젝트 없음)</span>}
              </p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => setChatInput(s)} className="rounded-full border border-[var(--border)] bg-[var(--surface-2)] px-3 py-1 text-xs text-[var(--text-dim)] hover:bg-[var(--surface-3)]">
                    {s}
                  </button>
                ))}
              </div>
              <div className="h-72 space-y-3 overflow-y-auto rounded-xl bg-[var(--surface-2)] p-3 ring-1 ring-[var(--border)]">
                {messages.length === 0 && <p className="text-xs text-[var(--text-faint)]">예: &ldquo;쇼츠로 만들어줘&rdquo;, &ldquo;스펙트럼으로 바꿔줘&rdquo;</p>}
                {messages.map((m, i) => (
                  <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
                    <span className={`inline-block max-w-[85%] rounded-2xl px-3 py-2 text-sm ${m.role === "user" ? "bg-indigo-500/80 text-white" : "bg-[var(--surface-2)]"}`}>
                      {m.text}
                    </span>
                  </div>
                ))}
                {agentBusy && <p className="text-xs text-[var(--text-dim)]">에이전트가 생각 중…</p>}
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

              <div className="space-y-2 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-3">
                <h3 className="flex items-center gap-2 text-sm font-medium">
                  🎥 AI 배경 영상
                  {settings && !settings.video_key_set && (
                    <span className="text-[11px] text-amber-300">(⚙️ 영상 키 필요)</span>
                  )}
                </h3>
                <p className="text-[11px] text-[var(--text-dim)]">
                  프롬프트로 AI 영상 클립을 만들어 배경에 깔고 그 위에 비주얼라이저·자막을 얹어 재렌더합니다.
                </p>
                <div className="flex gap-2">
                  <input
                    value={aiPrompt}
                    onChange={(e) => setAiPrompt(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && !aiVideoBusy && generateAiVideo()}
                    placeholder="예: 네온 도시 야경을 천천히 비행하는 시점"
                    className={inputCls}
                  />
                  <button
                    onClick={generateAiVideo}
                    disabled={aiVideoBusy}
                    className="shrink-0 rounded-lg bg-fuchsia-500 px-4 py-2 text-sm font-medium text-white hover:bg-fuchsia-400 disabled:opacity-50"
                  >
                    {aiVideoBusy ? "생성 중…" : "생성"}
                  </button>
                </div>
              </div>
            </Card>
          )}
        </section>

        {/* 오른쪽 */}
        <section className="space-y-6 lg:sticky lg:top-24 lg:self-start">
          <Card title="결과 미리보기">
            {!job && (
              <div className="grid h-56 place-items-center rounded-xl border border-dashed border-[var(--border)] text-sm text-[var(--text-faint)]">
                생성하면 여기에 영상이 표시됩니다 🎥
              </div>
            )}
            {job && busy && (
              <div className="space-y-3">
                <div className="flex items-center justify-between text-sm text-[var(--text-dim)]">
                  <span className="flex items-center gap-2">
                    <Spinner /> {job.stage ? job.stage : job.status === "queued" ? "대기 중…" : "렌더링 중…"}
                  </span>
                  {job.status === "running" && !job.stage && job.progress > 0 && (
                    <span className="tabular-nums text-[var(--text-dim)]">{job.progress}%</span>
                  )}
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--surface-2)]">
                  {job.status === "running" && !job.stage && job.progress > 0 ? (
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-indigo-400 to-fuchsia-400 transition-[width] duration-500"
                      style={{ width: `${job.progress}%` }}
                    />
                  ) : (
                    <div className="h-full w-1/3 animate-[loading_1.2s_ease-in-out_infinite] rounded-full bg-gradient-to-r from-indigo-400 to-fuchsia-400" />
                  )}
                </div>
                <button
                  onClick={() => cancelJob(job.id)}
                  className="rounded-lg bg-[var(--surface-2)] px-3 py-1.5 text-xs text-[var(--text-dim)] hover:bg-red-500/30 hover:text-white"
                >
                  ✕ 취소
                </button>
              </div>
            )}
            {job?.status === "cancelled" && (
              <p className="text-sm text-[var(--text-dim)]">취소된 작업입니다.</p>
            )}
            {job?.status === "error" && (
              <div className="space-y-2">
                <p className="text-sm text-red-400">렌더 실패: {job.error}</p>
                {job.log && <pre className="max-h-48 overflow-auto rounded-lg bg-[var(--code-bg)] p-3 text-xs whitespace-pre-wrap text-[var(--text-dim)]">{job.log}</pre>}
              </div>
            )}
            {job?.status === "done" && job.video && (
              <div className="space-y-3">
                <video src={`${API}/api/jobs/${job.id}/video`} controls className="mx-auto max-h-[68vh] w-full rounded-xl bg-black" />
                <div className="flex flex-wrap gap-2 text-sm">
                  <a href={`${API}/api/jobs/${job.id}/video`} download className="rounded-lg bg-[var(--surface-2)] px-3 py-2 hover:bg-[var(--surface-3)]">⬇ 영상</a>
                  {job.thumb && <a href={`${API}/api/jobs/${job.id}/thumb`} download className="rounded-lg bg-[var(--surface-2)] px-3 py-2 hover:bg-[var(--surface-3)]">⬇ 썸네일</a>}
                  <button onClick={() => setMode("ai")} className="rounded-lg bg-indigo-500/80 px-3 py-2 text-white hover:bg-indigo-500">✨ AI로 수정</button>
                  <button onClick={() => deleteJob(job.id)} className="rounded-lg bg-[var(--surface-2)] px-3 py-2 text-[var(--text-dim)] hover:bg-red-500/30 hover:text-white">🗑 삭제</button>
                </div>
              </div>
            )}
          </Card>

          {job?.status === "done" && (
            <Card title="🚀 유튜브 발행">
              <PublishPanel
                jobId={job.id}
                llmKeySet={!!settings?.llm_key_set}
                onToast={toast}
                onRefresh={refreshRecent}
              />
            </Card>
          )}

          <Card title="최근 작업">
            {(jobStats.running > 0 || jobStats.queued > 0) && (
              <div className="flex flex-wrap gap-2 text-[11px]">
                {jobStats.running > 0 && (
                  <span className="rounded-full bg-indigo-500/20 px-2 py-0.5 text-indigo-300">▶ 진행중 {jobStats.running}</span>
                )}
                {jobStats.queued > 0 && (
                  <span className="rounded-full bg-[var(--surface-3)] px-2 py-0.5 text-[var(--text-dim)]">⏳ 대기 {jobStats.queued}</span>
                )}
                <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-emerald-300">✓ 완료 {jobStats.done}</span>
                {jobStats.error > 0 && (
                  <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-red-300">✕ 실패 {jobStats.error}</span>
                )}
              </div>
            )}
            {recent.length > 0 && (
              <div className="flex items-center gap-2">
                <input
                  value={recentSearch}
                  onChange={(e) => setRecentSearch(e.target.value)}
                  placeholder="제목 검색…"
                  className={`${inputCls} flex-1`}
                />
                <select value={recentFilter} onChange={(e) => setRecentFilter(e.target.value)} className={`${inputCls} w-24`}>
                  <option value="all">전체</option>
                  <option value="done">완료</option>
                  <option value="running">진행중</option>
                  <option value="error">실패</option>
                </select>
              </div>
            )}
            {recent.length === 0 ? (
              <p className="text-xs text-[var(--text-faint)]">아직 없음</p>
            ) : filteredRecent.length === 0 ? (
              <p className="text-xs text-[var(--text-faint)]">검색 결과 없음</p>
            ) : (
              <div className="grid grid-cols-3 gap-2">
                {filteredRecent.slice(0, 12).map((r) => (
                  <div
                    key={r.id}
                    onClick={() => openJob(r.id)}
                    title={r.title}
                    className="group relative cursor-pointer overflow-hidden rounded-lg ring-1 ring-[var(--border)] hover:ring-indigo-400"
                  >
                    {r.thumb ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={`${API}/api/jobs/${r.id}/thumb`} alt="" className="aspect-video w-full object-cover" />
                    ) : (
                      <div className="grid aspect-video place-items-center bg-[var(--surface-2)] text-[10px] text-[var(--text-dim)]">
                        {r.status === "error" ? "실패" : r.status === "cancelled" ? "취소됨" : r.status}
                      </div>
                    )}
                    <span className="absolute inset-x-0 bottom-0 truncate bg-black/60 px-1 py-0.5 text-[10px] text-[var(--text)]">
                      {r.shorts ? "📱 " : ""}{r.title || r.id}
                    </span>
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteJob(r.id); }}
                      title="삭제"
                      className="absolute right-1 top-1 hidden h-5 w-5 place-items-center rounded bg-black/60 text-[10px] text-white hover:bg-red-500 group-hover:grid"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </section>
      </main>
    </div>
  );
}
