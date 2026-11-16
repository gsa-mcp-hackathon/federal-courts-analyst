import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { MotionConfig } from "motion/react";
import "@fontsource-variable/public-sans";
import "@fontsource-variable/source-serif-4";
import "@fontsource/ibm-plex-mono/400.css";
import "./styles.css";
import { router } from "./router";
import { applyTheme, storedTheme } from "./lib/theme";

applyTheme(storedTheme());

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Published figures change only when the data is rebuilt.
      staleTime: 10 * 60_000,
      retry: (count, err) => count < 2 && !(err as { status?: number }).status,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* Honour prefers-reduced-motion in motion's JS animations (transforms
          and layout); styles.css covers CSS animations and transitions. */}
      <MotionConfig reducedMotion="user">
        <RouterProvider router={router} />
      </MotionConfig>
    </QueryClientProvider>
  </StrictMode>,
);
