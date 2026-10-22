import { Component, useState, type ErrorInfo, type ReactNode } from "react";
import { Link, Outlet } from "@tanstack/react-router";
import { applyTheme, effectiveDark, storedTheme, type Theme } from "@/lib/theme";
import { Icon } from "./Icon";

const NAV = [
  { to: "/", label: "Ask" },
  { to: "/explore", label: "Explore" },
  { to: "/editions", label: "Edition Tracker" },
  { to: "/requests", label: "My requests" },
  { to: "/library", label: "Library" },
  { to: "/eval", label: "Evaluation" },
  { to: "/methodology", label: "Methodology" },
] as const;

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  const dark = theme === "dark" || (theme === "system" && effectiveDark());
  return (
    <button
      type="button"
      onClick={() => {
        const next: Theme = dark ? "light" : "dark";
        applyTheme(next);
        setTheme(next);
      }}
      className="rounded-md p-2 text-ink-2 hover:bg-paper-2 hover:text-ink"
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
    >
      <Icon name={dark ? "sun" : "moon"} />
    </button>
  );
}

export function Layout() {
  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-2 focus:z-50 focus:rounded focus:bg-card focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="border-b border-rule bg-paper/90 backdrop-blur supports-[backdrop-filter]:bg-paper/75">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
          <Link to="/" className="font-serif text-lg font-semibold tracking-tight text-ink">
            Federal Courts Analyst
          </Link>
          <nav aria-label="Main" className="flex flex-1 flex-wrap gap-1 text-sm">
            {NAV.map((n) => (
              <Link
                key={n.to}
                to={n.to}
                activeOptions={{ exact: n.to === "/" }}
                className="rounded-md px-2.5 py-1.5 text-ink-2 hover:bg-paper-2 hover:text-ink"
                activeProps={{
                  className: "bg-paper-2 font-medium text-ink",
                  "aria-current": "page",
                }}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <ThemeToggle />
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 sm:py-8">
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
      <footer className="border-t border-rule text-sm text-muted">
        <div className="mx-auto flex max-w-7xl flex-wrap gap-x-6 gap-y-1 px-4 py-4 sm:px-6">
          <span>
            Official figures from uscourts.gov tables (Judicial Business; Judicial Facts and
            Figures) and the FJC Integrated Database. Every number links to its table and edition.
          </span>
          <Link to="/demo" className="underline underline-offset-2">
            Presentation mode
          </Link>
          <Link to="/staff" className="underline underline-offset-2">
            Statistics office (simulated)
          </Link>
        </div>
      </footer>
    </div>
  );
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[fca] render error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="mx-auto max-w-xl rounded-lg border border-rule bg-card p-6">
        <h1 className="font-serif text-xl font-semibold">This page hit a problem</h1>
        <p className="mt-2 text-ink-2">
          Nothing was lost. Reload the page, or go back and try another view.
        </p>
        <button
          type="button"
          className="mt-4 rounded border border-rule px-3 py-1.5 hover:bg-paper-2"
          onClick={() => this.setState({ error: null })}
        >
          Try again
        </button>
      </div>
    );
  }
}

export function PageHeader({
  title,
  lede,
  children,
}: {
  title: string;
  lede?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          {title}
        </h1>
        {lede && <p className="mt-2 text-lg text-ink-2">{lede}</p>}
      </div>
      {children}
    </div>
  );
}
