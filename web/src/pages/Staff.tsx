// The statistics office's screen (ADR 0013, simulated): the inquiry queue,
// one row per revision with how many requests wait on it; recording a
// response; approving answers into the library; the audit log. Needs the
// staff token (DESK_STAFF_TOKEN), kept for this browser tab only.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { desk, staffToken } from "@/api/desk";
import type { InquiryView } from "@/api/types.gen";
import { PageHeader } from "@/components/Layout";
import {
  DeskError,
  OutcomeView,
  RequestAnswer,
  RequestHeader,
  statusLabel,
} from "@/components/desk";
import { EmptyState, Loading } from "@/components/States";
import { editionLabel, fmtValue } from "@/lib/format";

export function StaffPage() {
  const [token, setToken] = useState(staffToken.get());
  const [draft, setDraft] = useState("");
  if (!token) {
    return (
      <div className="mx-auto max-w-xl">
        <PageHeader
          title="Statistics office (simulated)"
          lede="The staff side of the request desk. A teammate plays the office in the sandbox."
        />
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            staffToken.set(draft.trim() || null);
            setToken(draft.trim() || null);
          }}
        >
          <label htmlFor="staff-token" className="sr-only">
            Staff token
          </label>
          <input
            id="staff-token"
            type="password"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Staff token (DESK_STAFF_TOKEN)"
            className="flex-1 rounded-md border border-rule bg-card px-3 py-2 text-ink"
          />
          <button
            type="submit"
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-ink"
          >
            Open
          </button>
        </form>
      </div>
    );
  }
  return (
    <StaffDesk
      onSignOut={() => {
        staffToken.set(null);
        setToken(null);
      }}
    />
  );
}

function StaffDesk({ onSignOut }: { onSignOut: () => void }) {
  const client = useQueryClient();
  const refresh = () => void client.invalidateQueries({ queryKey: ["desk"] });
  const queue = useQuery({ queryKey: ["desk", "staff", "queue"], queryFn: desk.staff.inquiries });
  const requests = useQuery({
    queryKey: ["desk", "staff", "requests"],
    queryFn: () => desk.staff.requests(),
  });
  const audit = useQuery({ queryKey: ["desk", "staff", "audit"], queryFn: desk.staff.audit });
  const publish = useMutation({ mutationFn: desk.staff.publish, onSuccess: refresh });
  const check = useMutation({ mutationFn: desk.staff.checkStaleness, onSuccess: refresh });
  const forbidden = queue.error ?? requests.error;
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Statistics office (simulated)"
        lede="Inquiries about revised figures, one per revision, most-asked first. Responses go to everyone waiting and show in the read tools, labelled as simulated."
      >
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => check.mutate()}
            className="rounded-md border border-rule px-3 py-1.5 text-sm text-ink hover:bg-paper-2"
          >
            Check for revised figures
          </button>
          <button
            type="button"
            onClick={onSignOut}
            className="rounded-md border border-rule px-3 py-1.5 text-sm text-ink hover:bg-paper-2"
          >
            Sign out
          </button>
        </div>
      </PageHeader>
      {check.data && (
        <p role="status" className="mb-4 text-sm text-ink-2">
          Checked {check.data.data.citations_checked} citations:{" "}
          {check.data.data.library_entries_flagged} library answers flagged,{" "}
          {check.data.data.updates_created} askers notified.
        </p>
      )}
      {forbidden && <DeskError error={forbidden} />}

      <section aria-label="Inquiry queue" className="mb-10">
        <h2 className="mb-3 font-serif text-2xl font-semibold text-ink">Inquiry queue</h2>
        {queue.isLoading && <Loading />}
        {queue.data?.data?.inquiries.length === 0 && <EmptyState title="No inquiries yet" />}
        <ul className="space-y-4">
          {queue.data?.data?.inquiries.map((i) => (
            <li key={i.id}>
              <InquiryCard inquiry={i} onDone={refresh} />
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Requests" className="mb-10">
        <h2 className="mb-3 font-serif text-2xl font-semibold text-ink">Requests</h2>
        {publish.data?.data && <OutcomeView outcome={publish.data.data} />}
        {publish.error && <DeskError error={publish.error} />}
        <ul className="mt-3 space-y-3">
          {requests.data?.data?.requests.map((r) => (
            <li key={r.id} className="space-y-2 rounded-lg border border-rule bg-card p-3">
              <RequestHeader request={r} />
              <RequestAnswer request={r} />
              {["office_responded", "verified", "watching"].includes(r.status) && r.answer && (
                <button
                  type="button"
                  onClick={() => publish.mutate(r.id)}
                  className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-ink"
                >
                  Approve and publish to the library
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Audit log">
        <h2 className="mb-3 font-serif text-2xl font-semibold text-ink">Audit log</h2>
        <div className="overflow-x-auto rounded-lg border border-rule bg-card">
          <table className="w-full text-sm">
            <thead className="bg-paper-2 text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-3 py-2">When</th>
                <th className="px-3 py-2">Who</th>
                <th className="px-3 py-2">Tool</th>
                <th className="px-3 py-2">Record</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {audit.data?.data?.events.map((e) => (
                <tr key={e.id} className="border-t border-rule">
                  <td className="num px-3 py-1.5 text-ink-2">
                    {new Date(e.at).toLocaleTimeString()}
                  </td>
                  <td className="px-3 py-1.5">{e.actor}</td>
                  <td className="px-3 py-1.5 font-mono text-xs">{e.tool}</td>
                  <td className="px-3 py-1.5 font-mono text-xs">{e.record}</td>
                  <td className="px-3 py-1.5 text-ink-2">
                    {e.before ? statusLabel(e.before) : "new"} →{" "}
                    {e.after ? statusLabel(e.after) : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function InquiryCard({ inquiry, onDone }: { inquiry: InquiryView; onDone: () => void }) {
  const [outcome, setOutcome] = useState<"confirmed" | "corrected">("confirmed");
  const [text, setText] = useState("");
  const respond = useMutation({
    mutationFn: () => desk.staff.respond(inquiry.id, outcome, text),
    onSuccess: onDone,
  });
  return (
    <article className="space-y-3 rounded-lg border border-rule bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-mono text-sm text-muted">Inquiry #{inquiry.id}</p>
          <p className="font-medium text-ink">
            Why did FY{inquiry.fiscal_year} {inquiry.measure_label.toLowerCase()} (
            {inquiry.court_name}) change from{" "}
            <span className="num">{fmtValue(inquiry.from_value)}</span> (
            {editionLabel(inquiry.from_edition)}) to{" "}
            <span className="num">{fmtValue(inquiry.to_value)}</span> (
            {editionLabel(inquiry.to_edition)})?
          </p>
          <p className="text-xs text-muted">
            Would go to {inquiry.route_label}. {inquiry.delivery}
          </p>
        </div>
        <span className="rounded-full bg-paper-2 px-2.5 py-0.5 text-sm font-medium text-ink">
          {inquiry.waiting_requests} request{inquiry.waiting_requests === 1 ? "" : "s"} waiting
        </span>
      </div>
      {inquiry.response ? (
        <p className="rounded bg-paper-2 px-2 py-1 text-sm text-ink-2">
          <span className="font-medium text-ink">Responded ({inquiry.response.outcome}):</span>{" "}
          {inquiry.response.text}
        </p>
      ) : (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            respond.mutate();
          }}
        >
          <fieldset className="flex gap-4 text-sm">
            <legend className="sr-only">Outcome</legend>
            {(["confirmed", "corrected"] as const).map((o) => (
              <label key={o} className="flex items-center gap-1.5">
                <input
                  type="radio"
                  name={`outcome-${inquiry.id}`}
                  checked={outcome === o}
                  onChange={() => setOutcome(o)}
                />
                {o === "confirmed" ? "Confirm the figure" : "Correct the figure"}
              </label>
            ))}
          </fieldset>
          <label htmlFor={`response-${inquiry.id}`} className="block text-sm text-ink-2">
            The office's explanation (written by the person playing the office)
          </label>
          <textarea
            id={`response-${inquiry.id}`}
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="w-full rounded-md border border-rule bg-paper p-2 text-sm text-ink"
          />
          <button
            type="submit"
            disabled={!text.trim() || respond.isPending}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-ink disabled:opacity-40"
          >
            Record response
          </button>
          {respond.error && <DeskError error={respond.error} />}
        </form>
      )}
    </article>
  );
}
