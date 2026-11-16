// Presentation mode: the demo storyline step by step, keyboard-driven, from
// the live agent or a recorded stream. If the live stream fails, the step
// switches to the recording by itself (demo insurance).
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { Link } from "@tanstack/react-router";
import { ask, parseRecorded, replay } from "@/api/sse";
import { initialTurn, reduceTurn, type TurnState } from "@/api/turn";
import type { AgentEvent } from "@/api/types.gen";
import { Icon } from "@/components/Icon";
import { AnswerView } from "./Ask";

interface Step {
  title: string;
  body: string;
  question?: string;
  recording?: string;
  link?: { to: string; label: string };
}

export const STEPS: Step[] = [
  {
    title: "One number, two answers",
    body: "National weighted civil filings per judgeship for FY2020 were first published as 554. Today's edition says 322. Both are official. This service always says which one it is quoting, and why they differ.",
    link: {
      to: "/editions/weighted-civil-filings-per-judgeship/national/2020",
      label: "Open the Edition Tracker",
    },
  },
  {
    title: "Ask why",
    body: "The agent works through the server's tools: explain the change, find the cases behind it, and pull example dockets. Every figure carries its edition.",
    question:
      "Why did weighted civil filings per judgeship drop so much for FY2020, and can you show me a few example MDL dockets from N.D. Fla. I could look up on CourtListener?",
    recording: "/demo/fy2020-storyline.sse",
  },
  {
    title: "Where the work is",
    body: "Which districts are over 600 weighted filings per judgeship, according to which edition? One click, one edition, no mixing.",
    link: {
      to: "/explore?measure=weighted-filings-per-judgeship&fy=2025&over=600",
      label: "Open Explore, over 600",
    },
  },
  {
    title: "What it won't do",
    body: "No judge rankings and no party names: the data has neither, by policy. The service says so and offers a district-level question instead, without calling a model.",
    question: "Rank the judges in S.D.N.Y. by how fast they close cases",
    recording: "/demo/judge-decline.sse",
  },
];

type Mode = "replay" | "live";

export function DemoPage() {
  const [i, setI] = useState(0);
  const [mode, setMode] = useState<Mode>("replay");
  const [note, setNote] = useState<string | null>(null);
  const [turn, dispatch] = useReducer(
    (s: TurnState, a: { reset: string } | AgentEvent) =>
      "reset" in a ? initialTurn(a.reset) : reduceTurn(s, a),
    initialTurn(),
  );
  const ctrl = useRef<AbortController | null>(null);
  const step = STEPS[i]!;

  const play = useCallback(async (s: Step, m: Mode) => {
    ctrl.current?.abort();
    if (!s.question) return dispatch({ reset: "" });
    const c = new AbortController();
    ctrl.current = c;
    setNote(null);
    dispatch({ reset: s.question });
    const playRecording = async () => {
      const text = await fetch(s.recording!).then((r) => r.text());
      await replay(parseRecorded(text), dispatch, { signal: c.signal, speed: 1.5 });
    };
    if (m === "replay" || !s.question) return playRecording();
    try {
      await ask(s.question, dispatch, c.signal);
    } catch {
      if (c.signal.aborted) return;
      setNote("The live answer failed; playing the recording instead.");
      dispatch({ reset: s.question });
      await playRecording();
    }
  }, []);

  useEffect(() => {
    // Start from a callback, not the effect body (no synchronous setState).
    const t = setTimeout(() => void play(step, mode), 0);
    return () => {
      clearTimeout(t);
      ctrl.current?.abort();
    };
  }, [step, mode, play]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") {
        e.preventDefault();
        setI((x) => Math.min(STEPS.length - 1, x + 1));
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault();
        setI((x) => Math.max(0, x - 1));
      } else if (e.key.toLowerCase() === "l") setMode("live");
      else if (e.key.toLowerCase() === "r") setMode("replay");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="num text-muted" aria-live="polite">
          Step {i + 1} of {STEPS.length}
        </p>
        <div className="flex items-center gap-2">
          <span className="text-muted">Source:</span>
          {(["replay", "live"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-full border px-3 py-1 ${mode === m ? "border-accent bg-accent text-accent-ink" : "border-rule"}`}
            >
              {m === "replay" ? "Recorded" : "Live agent"}
            </button>
          ))}
          <span className="hidden text-muted sm:inline">← → to move · L live · R recorded</span>
        </div>
      </div>
      <h1 className="font-serif text-4xl font-semibold tracking-tight sm:text-5xl">{step.title}</h1>
      <p className="mt-3 max-w-3xl text-xl text-ink-2">{step.body}</p>
      {step.link && (
        <Link
          to={step.link.to}
          className="mt-5 inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 font-medium text-accent-ink"
        >
          {step.link.label} <Icon name="chevron" />
        </Link>
      )}
      {note && <p className="mt-4 text-sm text-warning">{note}</p>}
      {step.question && turn.question && (
        <div className="mt-8">
          <AnswerView turn={turn} live />
        </div>
      )}
      <div className="mt-10 flex justify-between">
        <button
          type="button"
          disabled={i === 0}
          onClick={() => setI((x) => Math.max(0, x - 1))}
          className="rounded-lg border border-rule px-4 py-2 disabled:opacity-40"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={i === STEPS.length - 1}
          onClick={() => setI((x) => Math.min(STEPS.length - 1, x + 1))}
          className="rounded-lg bg-accent px-4 py-2 font-medium text-accent-ink disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
