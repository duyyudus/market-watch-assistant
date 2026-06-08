type CacheEntry<T> = {
  value?: T;
  expiresAt: number;
  inFlight?: Promise<T>;
};

export function createResourceCache(options: { ttlMs: number; now?: () => number }) {
  const now = options.now ?? Date.now;
  const entries = new Map<string, CacheEntry<unknown>>();

  return {
    async get<T>(key: string, loader: () => Promise<T>): Promise<T> {
      const entry = entries.get(key) as CacheEntry<T> | undefined;
      if (entry?.inFlight) {
        return entry.inFlight;
      }
      if (entry && entry.value !== undefined && entry.expiresAt > now()) {
        return entry.value;
      }
      const inFlight = loader().then((value) => {
        entries.set(key, { value, expiresAt: now() + options.ttlMs });
        return value;
      }).catch((error) => {
        entries.delete(key);
        throw error;
      });
      entries.set(key, { ...entry, expiresAt: 0, inFlight });
      return inFlight;
    },
    invalidate(key?: string) {
      if (key) {
        entries.delete(key);
      } else {
        entries.clear();
      }
    },
  };
}

export function debounceAsync<T>(fn: () => Promise<T>, delayMs: number) {
  let timeout: ReturnType<typeof setTimeout> | null = null;
  let pending: Promise<T> | null = null;

  return () => {
    if (pending) {
      return pending;
    }
    pending = new Promise<T>((resolve, reject) => {
      timeout = setTimeout(() => {
        timeout = null;
        fn()
          .then(resolve, reject)
          .finally(() => {
            pending = null;
          });
      }, delayMs);
    });
    return pending;
  };
}
