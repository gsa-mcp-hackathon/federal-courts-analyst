// Resolved design tokens for SVG charts (presentation attributes need real
// colors), updated when the theme changes.
import { useEffect, useState } from "react";

export const TOKEN_NAMES = [
  "paper",
  "card",
  "ink",
  "ink-2",
  "muted",
  "rule",
  "accent",
  "revision",
  "revision-bg",
  "revision-rule",
  "seq-1",
  "seq-2",
  "seq-3",
  "seq-4",
  "pole-up",
  "pole-down",
  "chart-grid",
  "good",
  "warning",
  "critical",
] as const;
export type Tokens = Record<(typeof TOKEN_NAMES)[number], string>;

export function readTokens(): Tokens {
  const cs = getComputedStyle(document.documentElement);
  return Object.fromEntries(
    TOKEN_NAMES.map((n) => [n, cs.getPropertyValue(`--${n}`).trim() || "#888"]),
  ) as Tokens;
}

export function useTokens(): Tokens {
  const [tokens, setTokens] = useState<Tokens>(readTokens);
  useEffect(() => {
    const update = () => setTokens(readTokens());
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener?.("change", update);
    return () => {
      mo.disconnect();
      mq?.removeEventListener?.("change", update);
    };
  }, []);
  return tokens;
}
