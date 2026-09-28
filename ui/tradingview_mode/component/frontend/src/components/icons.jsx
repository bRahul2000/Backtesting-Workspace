import React from "react";

// Original line icons, 18x18, stroke-based.
const paths = {
  crosshair: <><path d="M9 2v14M2 9h14" /><circle cx="9" cy="9" r="2.2" /></>,
  magnet: <><path d="M4 3v6a5 5 0 0 0 10 0V3" /><path d="M4 6h3M11 6h3" /></>,
  trend: <><path d="M3 15 15 3" /><circle cx="3" cy="15" r="1.4" /><circle cx="15" cy="3" r="1.4" /></>,
  hline: <><path d="M2 9h14" /><circle cx="9" cy="9" r="1.4" /></>,
  vline: <><path d="M9 2v14" /><circle cx="9" cy="9" r="1.4" /></>,
  rect: <rect x="3" y="4.5" width="12" height="9" rx="1" />,
  text: <><path d="M4 4h10M9 4v11" /></>,
  measure: <><path d="M3 15 15 3M5.5 12.5l1.5 1.5M8 10l1.5 1.5M10.5 7.5 12 9" /></>,
  trash: <><path d="M3.5 5h11M7 5V3.5h4V5M5 5l.8 10h6.4L13 5" /></>,
  fit: <><path d="M3 7V3h4M15 7V3h-4M3 11v4h4M15 11v4h-4" /></>,
  latest: <><path d="M4 4l5 5-5 5M10 4l5 5-5 5" /></>,
  chevron: <path d="M5 7l4 4 4-4" />,
  plus: <path d="M9 3v12M3 9h12" />,
  gear: <><circle cx="9" cy="9" r="2.4" /><path d="M9 1.8v2.2M9 14v2.2M1.8 9h2.2M14 9h2.2M3.9 3.9l1.6 1.6M12.5 12.5l1.6 1.6M3.9 14.1l1.6-1.6M12.5 5.5l1.6-1.6" /></>,
  calendar: <><rect x="2.5" y="3.5" width="13" height="12" rx="1.2" /><path d="M2.5 7.5h13M6 2v3M12 2v3" /></>,
  eye: <><path d="M1.8 9S4.5 4 9 4s7.2 5 7.2 5-2.7 5-7.2 5S1.8 9 1.8 9Z" /><circle cx="9" cy="9" r="2" /></>,
  eyeOff: <><path d="M1.8 9S4.5 4 9 4s7.2 5 7.2 5-2.7 5-7.2 5S1.8 9 1.8 9Z" /><path d="M3 15 15 3" /></>,
  close: <path d="M4.5 4.5l9 9M13.5 4.5l-9 9" />,
  fx: <><path d="M6.5 15c1.5 0 2-1 2.3-3l1-6c.3-1.7.9-2.5 2.2-2.5" /><path d="M5.5 8h6" /></>,
  collapse: <path d="M5 11l4-4 4 4" />,
  expand: <path d="M5 7l4 4 4-4" />,
};

export function Icon({ name, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" fill="none" stroke="currentColor"
      strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}
