import type { ResourceKey } from "../types/dashboard";

export function errorMessage(value: unknown) {
  return value instanceof Error ? value.message : "Failed to load data";
}

export async function settle<T>(key: ResourceKey, request: Promise<T>) {
  try {
    return { key, value: await request };
  } catch (error) {
    return { key, error: errorMessage(error) };
  }
}

