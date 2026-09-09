import { createContext, useContext, useEffect, useMemo, useState } from 'react';

/**
 * Wires the topbar search box to whatever the current screen lists.
 *
 * The input existed before this but was connected to nothing — a visible
 * control that silently did nothing. Every dashboard already holds its full row
 * set in state, so filtering is a client-side pass and needs no endpoint.
 *
 * A page opts in by calling `useSearch(placeholder)`. If no page has opted in,
 * the provider reports `active: false` and the layout hides the input rather
 * than showing a dead one.
 */
const SearchContext = createContext(null);

export function SearchProvider({ children }) {
  const [query, setQuery] = useState('');
  const [placeholder, setPlaceholder] = useState(null);

  const value = useMemo(
    () => ({ query, setQuery, placeholder, setPlaceholder, active: placeholder !== null }),
    [query, placeholder],
  );

  return <SearchContext.Provider value={value}>{children}</SearchContext.Provider>;
}

/** Used by the layout to render the control itself. */
export function useSearchBox() {
  const ctx = useContext(SearchContext);
  if (!ctx) throw new Error('useSearchBox must be used inside <SearchProvider>');
  return ctx;
}

/**
 * Used by a page to claim the search box. Returns the current query, lowercased
 * and trimmed, ready to match against. The query resets when the page unmounts
 * so a filter never leaks across a route change.
 */
export function useSearch(placeholder) {
  const ctx = useContext(SearchContext);
  const setPlaceholder = ctx?.setPlaceholder;
  const setQuery = ctx?.setQuery;

  useEffect(() => {
    if (!setPlaceholder || !setQuery) return undefined;
    setPlaceholder(placeholder);
    return () => {
      setPlaceholder(null);
      setQuery('');
    };
  }, [placeholder, setPlaceholder, setQuery]);

  return (ctx?.query || '').trim().toLowerCase();
}

/**
 * Convenience matcher: true when the query is empty, or when any of the given
 * fields contains it. Keeps the "no query shows everything" rule in one place
 * instead of repeated across three dashboards.
 */
export function matches(query, ...fields) {
  if (!query) return true;
  return fields.some((f) => String(f ?? '').toLowerCase().includes(query));
}
