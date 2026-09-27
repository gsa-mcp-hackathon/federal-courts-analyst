import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Court } from "@/api/types";

/** URL form of a court code: "national" for US, lower case otherwise. */
export const courtSlug = (code: string) => (code === "US" ? "national" : code.toLowerCase());
export const courtFromSlug = (slug: string) =>
  slug.toLowerCase() === "national" ? "US" : slug.toUpperCase();

export function useCourts() {
  return useQuery({ queryKey: ["courts"], queryFn: api.courts, staleTime: Infinity });
}

export function courtNames(courts: Court[] | undefined): Map<string, string> {
  return new Map((courts ?? []).map((c) => [c.code, c.citation ?? c.name]));
}

export function districts(courts: Court[] | undefined): Court[] {
  return (courts ?? []).filter((c) => c.level === "district");
}
