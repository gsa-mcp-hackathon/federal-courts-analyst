import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Link,
  redirect,
} from "@tanstack/react-router";
import { Layout } from "./components/Layout";
import { EmptyState } from "./components/States";
import { AskPage } from "./pages/Ask";

// Each page is its own chunk (the chart library loads only where needed).
const ExplorePage = lazyRouteComponent(() => import("./pages/Explore"), "ExplorePage");
const EditionsPage = lazyRouteComponent(() => import("./pages/Editions"), "EditionsPage");
const CourtPage = lazyRouteComponent(() => import("./pages/Court"), "CourtPage");
const EvaluationPage = lazyRouteComponent(() => import("./pages/Evaluation"), "EvaluationPage");
const MethodologyPage = lazyRouteComponent(() => import("./pages/Methodology"), "MethodologyPage");
const DemoPage = lazyRouteComponent(() => import("./pages/Demo"), "DemoPage");
const GalleryPage = lazyRouteComponent(() => import("./pages/Gallery"), "GalleryPage");
const RequestsPage = lazyRouteComponent(() => import("./pages/Requests"), "RequestsPage");
const LibraryPage = lazyRouteComponent(() => import("./pages/Library"), "LibraryPage");
const StaffPage = lazyRouteComponent(() => import("./pages/Staff"), "StaffPage");
import type { ExploreSearch } from "./pages/Explore";

const rootRoute = createRootRoute({
  component: Layout,
  notFoundComponent: () => (
    <EmptyState title="Page not found">
      <Link to="/" className="text-accent underline">
        Ask a question
      </Link>{" "}
      or{" "}
      <Link to="/explore" className="text-accent underline">
        explore the districts
      </Link>
      .
    </EmptyState>
  ),
});

const num = (v: unknown, lo: number, hi: number): number | undefined => {
  const n = Number(v);
  return Number.isInteger(n) && n >= lo && n <= hi ? n : undefined;
};

const askRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: () => <AskPage />,
});
const askReplayRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/ask/$turnId",
  component: function Replay() {
    const { turnId } = askReplayRoute.useParams();
    return <AskPage key={turnId} replayId={turnId} />;
  },
});
const exploreRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/explore",
  validateSearch: (s: Record<string, unknown>): ExploreSearch => ({
    measure: typeof s.measure === "string" ? s.measure : undefined,
    fy: num(s.fy, 2016, 2025),
    edition:
      s.edition === "first_published"
        ? "first_published"
        : s.edition === "latest"
          ? "latest"
          : undefined,
    over: num(s.over, 0, 100000),
  }),
  component: function Explore() {
    return <ExplorePage search={exploreRoute.useSearch()} />;
  },
});
const editionsIndex = createRoute({
  getParentRoute: () => rootRoute,
  path: "/editions",
  beforeLoad: () => {
    throw redirect({
      to: "/editions/$measure/$court/$fy",
      params: { measure: "weighted-civil-filings-per-judgeship", court: "national", fy: "2020" },
    });
  },
});
const editionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/editions/$measure/$court/$fy",
  component: function Editions() {
    const p = editionsRoute.useParams();
    const fy = num(p.fy, 2016, 2025) ?? 2020;
    return <EditionsPage measureSlug={p.measure} courtSlugParam={p.court} fy={fy} />;
  },
});
const courtRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/courts/$court",
  validateSearch: (s: Record<string, unknown>): { fy?: number } => ({ fy: num(s.fy, 2016, 2025) }),
  component: function Court() {
    const { court } = courtRoute.useParams();
    const { fy } = courtRoute.useSearch();
    return <CourtPage slug={court} fy={fy} />;
  },
});
const evalRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/eval",
  component: () => <EvaluationPage />,
});
const evalRunRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/eval/$runId",
  component: function Run() {
    return <EvaluationPage runId={evalRunRoute.useParams().runId} />;
  },
});
const methodologyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/methodology",
  component: MethodologyPage,
});
const demoRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/demo",
  component: DemoPage,
});
const requestsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/requests",
  component: RequestsPage,
});
const libraryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/library",
  component: LibraryPage,
});
const staffRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/staff",
  component: StaffPage,
});
const galleryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/dev/gallery",
  component: GalleryPage,
});

const routeTree = rootRoute.addChildren([
  askRoute,
  askReplayRoute,
  exploreRoute,
  editionsIndex,
  editionsRoute,
  courtRoute,
  evalRoute,
  evalRunRoute,
  methodologyRoute,
  demoRoute,
  requestsRoute,
  libraryRoute,
  staffRoute,
  galleryRoute,
]);

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  scrollRestoration: true,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
