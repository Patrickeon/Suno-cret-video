"use client";

import { useRef, useState } from "react";

export function Card({ title, step, children }: { title: string; step?: string; children: React.ReactNode }) {
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

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-neutral-400">{label}</span>
      {children}
    </label>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button onClick={() => onChange(!checked)} className="flex w-full items-center gap-3 text-left text-sm text-neutral-300">
      <span className={`relative h-5 w-9 shrink-0 rounded-full transition ${checked ? "bg-indigo-500" : "bg-white/15"}`}>
        <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${checked ? "left-[18px]" : "left-0.5"}`} />
      </span>
      {label}
    </button>
  );
}

export function Spinner() {
  return <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/20 border-t-indigo-400" />;
}

export function Dropzone({
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
