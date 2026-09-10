const common = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', 'aria-hidden': true };

export function UsersIcon() {
  return (
    <svg {...common}>
      <circle cx="9" cy="8" r="3.2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M3.5 19c.7-3 2.9-4.6 5.5-4.6s4.8 1.6 5.5 4.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M15.5 5.3a3.2 3.2 0 0 1 0 6.2M17.8 14.6c2.2.5 3.7 2 4.2 4.4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export function BriefcaseIcon() {
  return (
    <svg {...common}>
      <rect x="3" y="7.5" width="18" height="12" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8.5 7.5V6a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v1.5M3 12.5h18" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export function ShieldIcon() {
  return (
    <svg {...common}>
      <path
        d="M12 3.5 19 6v5.5c0 4.4-3 7.6-7 8.9-4-1.3-7-4.5-7-8.9V6l7-2.5Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M9 12l2 2 4-4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function CandidatesIcon() {
  return (
    <svg {...common}>
      <circle cx="8" cy="8" r="3" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="16.5" cy="9" r="2.3" stroke="currentColor" strokeWidth="1.6" />
      <path d="M2.5 19c.6-3 2.7-4.6 5.5-4.6s4.9 1.6 5.5 4.6M15 15c2.4.2 4 1.6 4.5 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export function CheckBadgeIcon() {
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8.5 12.2l2.3 2.3 4.7-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ClockIcon() {
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M12 7.5V12l3 2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/*
 * Chrome icons — used by the shell, empty states and table controls. These take
 * an optional `size` because they sit inline with text at several scales, where
 * the icons above are always rendered into a fixed 46px or 19px slot.
 */
function chrome(size) {
  return { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', 'aria-hidden': true };
}

export function SearchIcon({ size = 18 }) {
  return (
    <svg {...chrome(size)}>
      <circle cx="10.5" cy="10.5" r="6.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M15.5 15.5 20 20" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export function CloseIcon({ size = 18 }) {
  return (
    <svg {...chrome(size)}>
      <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function MenuIcon({ size = 20 }) {
  return (
    <svg {...chrome(size)}>
      <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

export function PlusIcon({ size = 16 }) {
  return (
    <svg {...chrome(size)}>
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" />
    </svg>
  );
}

export function CheckIcon({ size = 18 }) {
  return (
    <svg {...chrome(size)}>
      <path d="M5 12.5l4.5 4.5L19 7" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ChevronRightIcon({ size = 16 }) {
  return (
    <svg {...chrome(size)}>
      <path d="M9.5 5.5 16 12l-6.5 6.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * Sort affordance. `dir` of 'asc' / 'desc' dims the arrow pointing the other
 * way so the active direction reads at a glance; unsorted shows both at
 * equal weight.
 */
export function SortIcon({ size = 14, dir = null }) {
  return (
    <svg {...chrome(size)}>
      <path
        d="M8 10.5 12 6l4 4.5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={dir === 'desc' ? 0.25 : 1}
      />
      <path
        d="M8 13.5 12 18l4-4.5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={dir === 'asc' ? 0.25 : 1}
      />
    </svg>
  );
}

export function InboxIcon({ size = 22 }) {
  return (
    <svg {...chrome(size)}>
      <path
        d="M4 13.5 6 5.5h12l2 8v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-4Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path d="M4 13.5h4l1 2.5h6l1-2.5h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function SparkIcon({ size = 22 }) {
  return (
    <svg {...chrome(size)}>
      <path
        d="M12 3.5 13.9 9 19.5 11l-5.6 2-1.9 5.5L10.1 13 4.5 11l5.6-2 1.9-5.5Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function LockIcon({ size = 18 }) {
  return (
    <svg {...chrome(size)}>
      <rect x="5" y="10.5" width="14" height="9.5" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}
