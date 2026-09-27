import type { ReactNode } from "react";
import { ApiError } from "@/api/client";
import { Icon } from "./Icon";

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-paper-2 ${className}`} aria-hidden />;
}

export function Loading({ label = "Loading…", lines = 3 }: { label?: string; lines?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-2 py-4">
      <span className="sr-only">{label}</span>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={`h-4 ${i === lines - 1 ? "w-2/3" : "w-full"}`} />
      ))}
    </div>
  );
}

/** A placeholder the size of the chart that will replace it. */
export function ChartSkeleton({ height = 320 }: { height?: number }) {
  return (
    <div
      role="status"
      aria-label="Loading chart"
      className="animate-pulse rounded-lg border border-rule bg-card"
      style={{ height: height + 90 }}
    />
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-rule p-6 text-center text-muted">
      <p className="font-medium text-ink-2">{title}</p>
      {children && <div className="mt-1 text-sm">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const api = error instanceof ApiError ? error : null;
  const message =
    api?.body.message ??
    (error instanceof Error ? error.message : "Something went wrong loading this.");
  return (
    <div role="alert" className="rounded-lg border border-critical/40 bg-card p-4 text-sm">
      <p className="flex items-center gap-2 font-medium text-critical">
        <Icon name="caution" />
        {api && api.status === 422 ? "The server can't answer that as asked" : "Couldn't load this"}
      </p>
      <p className="mt-1 text-ink-2">{message}</p>
      {api?.body.suggested_next?.length ? (
        <p className="mt-1 text-muted">Try: {api.body.suggested_next.join("; ")}.</p>
      ) : null}
      {retry && (
        <button
          type="button"
          onClick={retry}
          className="mt-3 rounded border border-rule px-3 py-1 text-ink hover:bg-paper-2"
        >
          Try again
        </button>
      )}
    </div>
  );
}
