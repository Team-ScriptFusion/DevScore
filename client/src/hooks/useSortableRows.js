import { useMemo, useState } from 'react';

/**
 * Client-side table sorting. Every dashboard table already holds its full row
 * set in state, so sorting needs no endpoint and no pagination story.
 *
 * `columns` maps a column key to a value accessor. Nullish values always sort
 * last regardless of direction — an unscored candidate belongs at the bottom
 * whether you're looking for the strongest or the weakest, not floating to the
 * top as a zero.
 */
export default function useSortableRows(rows, columns, initial = null) {
  const [sort, setSort] = useState(initial); // { key, dir: 'asc' | 'desc' }

  const sorted = useMemo(() => {
    if (!sort || !columns[sort.key]) return rows;
    const get = columns[sort.key];
    const factor = sort.dir === 'asc' ? 1 : -1;

    return [...rows].sort((a, b) => {
      const av = get(a);
      const bv = get(b);
      const aNull = av === null || av === undefined || av === '';
      const bNull = bv === null || bv === undefined || bv === '';
      if (aNull && bNull) return 0;
      if (aNull) return 1;
      if (bNull) return -1;

      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * factor;
      return String(av).localeCompare(String(bv), undefined, { sensitivity: 'base' }) * factor;
    });
  }, [rows, sort, columns]);

  /** Cycles asc → desc → unsorted, so a column can always be un-picked. */
  function toggle(key) {
    setSort((current) => {
      if (!current || current.key !== key) return { key, dir: 'asc' };
      if (current.dir === 'asc') return { key, dir: 'desc' };
      return null;
    });
  }

  /** Maps to the `aria-sort` values a `<th>` expects. */
  function ariaSort(key) {
    if (sort?.key !== key) return 'none';
    return sort.dir === 'asc' ? 'ascending' : 'descending';
  }

  return { rows: sorted, sort, toggle, ariaSort, dirFor: (k) => (sort?.key === k ? sort.dir : null) };
}
