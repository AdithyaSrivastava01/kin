"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Paperclip,
  Upload,
  X,
} from "lucide-react";
import { Button } from "./ui/button";
import { Input, Select } from "./ui/input";
import { fmtBytes } from "../lib/format";
import { RELAY } from "../lib/constants";
import type { DocMeta, Patient } from "../lib/types";

export function UploadPanel() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [docs, setDocs] = useState<DocMeta[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(`${RELAY}/patients`)
      .then((r) => r.json())
      .then((rows: Patient[]) => {
        setPatients(rows);
        if (rows.length && !selected) setSelected(rows[0].patient_id);
      })
      .catch((e) => setError(`Couldn't load patients: ${e}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) return;
    fetch(`${RELAY}/documents/${selected}`)
      .then((r) => r.json())
      .then(setDocs)
      .catch(() => setDocs([]));
  }, [selected]);

  const upload = async () => {
    if (!file || !selected) return;
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const fd = new FormData();
      fd.append("patient_id", selected);
      fd.append("file", file);
      if (description) fd.append("description", description);

      const r = await fetch(`${RELAY}/upload`, { method: "POST", body: fd });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? `HTTP ${r.status}`);

      setSuccess(`Uploaded ${body.filename} (${fmtBytes(body.size_bytes)})`);
      setFile(null);
      setDescription("");
      if (fileInputRef.current) fileInputRef.current.value = "";

      const r2 = await fetch(`${RELAY}/documents/${selected}`);
      setDocs(await r2.json());
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const selectedPatient = patients.find((p) => p.patient_id === selected);

  return (
    <div className="flex flex-col gap-5">
      <div className="space-y-4">
        <Field label="Patient">
          <Select value={selected} onChange={(e) => setSelected(e.target.value)}>
            {patients.map((p) => (
              <option key={p.patient_id} value={p.patient_id}>
                {p.name} · {p.primary_language ?? "—"}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Document">
          <label className="group flex items-center gap-3 px-3.5 h-10 bg-surface border border-dashed border-line hover:border-brand-400 hover:bg-brand-50/40 rounded-lg cursor-pointer transition-colors">
            <Paperclip
              size={15}
              className="text-ink-muted group-hover:text-brand-600 shrink-0"
            />
            <span className="text-sm text-ink-secondary truncate flex-1">
              {file ? file.name : "Choose a file…"}
            </span>
            {file && (
              <span className="font-mono text-2xs text-ink-tertiary shrink-0">
                {fmtBytes(file.size)}
              </span>
            )}
            <input
              ref={fileInputRef}
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="hidden"
            />
          </label>
        </Field>

        <Field label="Description" optional>
          <Input
            type="text"
            placeholder="e.g. lab report, intake form"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>

        <Button onClick={upload} disabled={busy || !file || !selected} className="w-full">
          <Upload size={15} />
          {busy ? "Uploading…" : "Upload document"}
        </Button>

        {error && (
          <Alert tone="danger" onDismiss={() => setError(null)}>
            <AlertCircle size={14} />
            {error}
          </Alert>
        )}
        {success && (
          <Alert tone="success" onDismiss={() => setSuccess(null)}>
            <CheckCircle2 size={14} />
            {success}
          </Alert>
        )}
      </div>

      {selectedPatient && (
        <div className="pt-5 border-t border-line">
          <div className="flex items-center justify-between mb-3">
            <span className="text-2xs font-semibold text-ink-tertiary uppercase tracking-[0.08em]">
              {selectedPatient.name}'s files
            </span>
            <span className="font-mono text-2xs text-ink-muted">{docs.length}</span>
          </div>
          {docs.length === 0 ? (
            <p className="text-xs text-ink-muted italic">No documents uploaded yet.</p>
          ) : (
            <ul className="space-y-2">
              {docs.map((d) => (
                <li
                  key={d.doc_id}
                  className="group flex items-center gap-3 px-3 h-11 bg-surface border border-line rounded-lg hover:border-line-strong hover:shadow-soft transition-all"
                >
                  <span className="flex items-center justify-center w-7 h-7 rounded-md bg-brand-50 text-brand-600 shrink-0">
                    <FileText size={13} />
                  </span>
                  <a
                    href={`${RELAY}/document/${d.doc_id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-medium text-ink-primary hover:text-brand-700 truncate flex-1 transition-colors"
                    title={d.description ?? d.filename}
                  >
                    {d.filename}
                  </a>
                  <span className="font-mono text-2xs text-ink-tertiary shrink-0">
                    {fmtBytes(d.size_bytes)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  optional,
  children,
}: {
  label: string;
  optional?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="flex items-center gap-2 text-2xs font-semibold text-ink-tertiary uppercase tracking-[0.08em] mb-2">
        {label}
        {optional && (
          <span className="text-ink-muted normal-case font-normal tracking-normal">
            optional
          </span>
        )}
      </span>
      {children}
    </label>
  );
}

function Alert({
  tone,
  onDismiss,
  children,
}: {
  tone: "success" | "danger";
  onDismiss?: () => void;
  children: React.ReactNode;
}) {
  const styles =
    tone === "danger"
      ? "bg-red-50 border-red-100 text-red-700"
      : "bg-emerald-50 border-emerald-100 text-emerald-700";
  return (
    <div
      className={`flex items-start gap-2 px-3 py-2.5 rounded-lg border text-xs leading-relaxed ${styles}`}
    >
      {children}
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="ml-auto opacity-60 hover:opacity-100 shrink-0"
          aria-label="Dismiss"
        >
          <X size={13} />
        </button>
      )}
    </div>
  );
}
