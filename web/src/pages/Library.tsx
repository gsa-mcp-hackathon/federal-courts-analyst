// The public library (ADR 0013): answers the statistics office approved,
// searchable by anyone. Entries citing a figure a newer edition revised say so.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { desk } from "@/api/desk";
import { PageHeader } from "@/components/Layout";
import { DeskError, LibraryCard, SANDBOX_NOTE } from "@/components/desk";
import { EmptyState, Loading } from "@/components/States";

export function LibraryPage() {
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const lib = useQuery({ queryKey: ["desk", "library", q], queryFn: () => desk.library({ q }) });
  const entries = lib.data?.data?.entries ?? [];
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title="Answer library"
        lede="Answers the statistics office approved, with every figure checked against its edition. The next person who asks gets the same answer."
      />
      <form
        className="mb-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(draft.trim());
        }}
      >
        <label htmlFor="library-q" className="sr-only">
          Search the library
        </label>
        <input
          id="library-q"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Search approved answers…"
          className="flex-1 rounded-md border border-rule bg-card px-3 py-2 text-ink"
        />
        <button
          type="submit"
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-ink"
        >
          Search
        </button>
      </form>
      <p className="mb-6 text-sm text-muted">{SANDBOX_NOTE}</p>
      {lib.isLoading && <Loading />}
      {lib.error && <DeskError error={lib.error} />}
      {!lib.isLoading && entries.length === 0 && (
        <EmptyState title={q ? "No approved answer matches" : "No approved answers yet"} />
      )}
      <div className="space-y-4">
        {entries.map((e) => (
          <LibraryCard key={e.id} entry={e} />
        ))}
      </div>
    </div>
  );
}
