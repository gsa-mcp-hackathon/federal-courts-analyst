// My requests (ADR 0013): every request the demo account made, its progress
// and the updates it received. Opening one marks its updates read.
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { desk, deskAccount } from "@/api/desk";
import { PageHeader } from "@/components/Layout";
import {
  AccountPicker,
  DeskError,
  RequestAnswer,
  RequestHeader,
  SANDBOX_NOTE,
  StatusTimeline,
  UpdatesList,
} from "@/components/desk";
import { EmptyState, Loading } from "@/components/States";

export function RequestsPage() {
  const [account, setAccount] = useState(deskAccount.get());
  const client = useQueryClient();
  const mine = useQuery({
    queryKey: ["desk", "mine", account],
    queryFn: desk.mine,
    enabled: account !== null,
    refetchInterval: 10_000,
  });
  const read = useMutation({
    mutationFn: (id: number) => desk.markRead(id),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["desk", "mine"] }),
  });
  const list = mine.data?.data;
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title="My requests"
        lede="Answers you asked the statistics office about, saved as verified copies, or asked to be notified about. Asking a question never creates one."
      />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <AccountPicker onChange={setAccount} />
        {list && list.unread_total > 0 && (
          <span className="rounded-full bg-accent px-2.5 py-0.5 text-sm font-medium text-accent-ink">
            {list.unread_total} new update{list.unread_total === 1 ? "" : "s"}
          </span>
        )}
      </div>
      <p className="mb-6 text-sm text-muted">{SANDBOX_NOTE}</p>
      {!account && <EmptyState title="Choose a demo account to see its requests" />}
      {mine.isLoading && <Loading />}
      {mine.error && <DeskError error={mine.error} />}
      {list && list.requests.length === 0 && (
        <EmptyState title="No requests yet">
          Ask a question, then pick an option under the answer.{" "}
          <Link to="/" className="text-accent underline">
            Ask a question
          </Link>
        </EmptyState>
      )}
      <ul className="space-y-4">
        {list?.requests.map((r) => (
          <li key={r.id}>
            <article
              className="space-y-3 rounded-lg border border-rule bg-card p-4"
              onFocus={() => r.unread > 0 && read.mutate(r.id)}
              onMouseEnter={() => r.unread > 0 && read.mutate(r.id)}
              tabIndex={0}
              aria-label={`Request ${r.id}`}
            >
              <RequestHeader request={r} />
              <StatusTimeline request={r} />
              {r.needs_reverification && (
                <p className="rounded border-l-4 border-l-warning bg-paper-2 px-2 py-1 text-sm text-ink-2">
                  A newer edition revised a figure in this answer.
                </p>
              )}
              <UpdatesList updates={r.updates} />
              <RequestAnswer request={r} />
            </article>
          </li>
        ))}
      </ul>
    </div>
  );
}
