import React, { useEffect, useRef } from "react";

// Anchored dropdown that closes on outside click or Escape.
export function Popover({ open, onClose, children, align = "left", width }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event) => {
      if (ref.current && !ref.current.parentElement.contains(event.target)) onClose();
    };
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);
  if (!open) return null;
  return <div ref={ref} className={`popover popover-${align}`} style={width ? { width } : undefined}>{children}</div>;
}
