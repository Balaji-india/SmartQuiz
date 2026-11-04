"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { useLoad } from "@/lib/use-load";
import { AuthedPage } from "@/components/shell";
import { Button, Card, ChainBadge, ErrorBox, Loading } from "@/components/ui";
import { listDocuments, uploadDocument } from "@/lib/api";
import type { DocumentOut } from "@/lib/types";

const POLL_MS = 3000;
const ACCEPT = ".pdf,.txt";

function StatusPill({ doc }: { doc: DocumentOut }) {
  if (doc.status === "ingesting")
    return <span className="rounded-full bg-paper px-3 py-1 text-xs font-semibold text-muted">Building textbook…</span>;
  if (doc.status === "failed") return <span className="rounded-full bg-bad-soft px-3 py-1 text-xs font-semibold text-bad">Failed</span>;
  return <span className="rounded-full bg-ok-soft px-3 py-1 text-xs font-semibold text-ok">Ready</span>;
}

function Documents() {
  const { data: docs, error, reload: load } = useLoad<DocumentOut[]>(listDocuments, "documents");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const ingesting = docs?.some((d) => d.status === "ingesting") ?? false;
  useEffect(() => {
    if (!ingesting) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [ingesting, load]);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    if (!/\.(pdf|txt)$/i.test(file.name)) {
      setUploadError("Only .pdf and .txt files are supported.");
      return;
    }
    setUploading(true);
    setUploadError(null);
    try {
      await uploadDocument(file);
      load();
    } catch (e) {
      setUploadError((e as Error).message);
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    upload(e.dataTransfer.files?.[0]);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Your documents</h1>
        <p className="mt-1 text-muted">Upload course notes. SmartQuiz turns them into a textbook of numbered, verified facts.</p>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`rounded-xl border-2 border-dashed p-6 text-center transition-colors sm:p-10 ${dragging ? "border-accent bg-warn-soft" : "border-line bg-card"}`}
      >
        <p className="font-display text-lg font-semibold">Drop a PDF or text file here</p>
        <p className="mt-1 text-sm text-muted">Course notes only, up to 25 MB. Do not upload personal data.</p>
        <input ref={input} type="file" accept={ACCEPT} className="sr-only" id="upload" onChange={(e) => upload(e.target.files?.[0])} />
        <Button className="mt-4" disabled={uploading} onClick={() => input.current?.click()}>
          {uploading ? "Uploading…" : "Choose file"}
        </Button>
        {uploadError && (
          <div className="mx-auto mt-4 max-w-md text-left">
            <ErrorBox message={uploadError} />
          </div>
        )}
      </div>

      {error && <ErrorBox message={error} onRetry={load} />}
      {!docs && !error && <Loading label="Loading your documents…" />}
      {docs && docs.length === 0 && <p className="text-muted">No documents yet. Upload your first chapter above.</p>}
      {docs && docs.length > 0 && (
        <ul className="grid gap-3">
          {docs.map((d) => (
            <li key={d.id}>
              <Card className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="truncate font-display text-lg font-semibold">{d.filename}</p>
                  <p className="mt-1 text-sm text-muted">
                    {d.status === "ingesting"
                      ? "Extracting and checking facts. This takes a few minutes for a chapter."
                      : d.status === "failed"
                        ? "Ingestion failed. Upload the same file again to retry."
                        : `${d.sections_count} sections · ${d.fact_count} facts`}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill doc={d} />
                  {d.status === "ready" && <ChainBadge status={d.chain_status} />}
                  {d.status === "ready" && (
                    <Link href={`/documents/${d.id}`} className="rounded-lg bg-navy px-4 py-2 text-sm font-semibold text-white hover:bg-navy-soft">
                      Open
                    </Link>
                  )}
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function HomePage() {
  return (
    <AuthedPage>
      <Documents />
    </AuthedPage>
  );
}
