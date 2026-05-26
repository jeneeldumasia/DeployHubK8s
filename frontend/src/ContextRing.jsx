import { useState, useRef, useEffect, useCallback } from "react";

const ITEMS = [
  { id: "dashboard",  label: "Home",       icon: "⌂" },
  { id: "projects",   label: "Projects",   icon: "◫" },
  { id: "logs",       label: "Logs",       icon: "≡" },
  { id: "monitoring", label: "Monitoring", icon: "◎" },
  { id: "info",       label: "Guide",      icon: "ℹ" },
  { id: "settings",   label: "Settings",   icon: "⚙" },
];

const START_DEG = 90;
const END_DEG   = 0;
const RADIUS    = 100;

function degToRad(d) { return (d * Math.PI) / 180; }

export default function ContextRing({ page, setPage, systemStatus = "running", activePulses = {} }) {
  const [open, setOpen] = useState(false);
  const ringRef = useRef(null);
  const closeTimer = useRef(null);

  const openRing  = useCallback(() => { clearTimeout(closeTimer.current); setOpen(true);  }, []);
  const closeRing = useCallback(() => { closeTimer.current = setTimeout(() => setOpen(false), 180); }, []);

  useEffect(() => {
    function onDown(e) {
      if (ringRef.current && !ringRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const step = (START_DEG - END_DEG) / (ITEMS.length - 1);

  return (
    <div
      ref={ringRef}
      className={`context-ring ${open ? "open" : ""}`}
      onMouseEnter={openRing}
      onMouseLeave={closeRing}
    >
      {ITEMS.map((item, i) => {
        // Calculate arc from 90 (top) down to 0 (right)
        const deg = START_DEG - step * i;
        const rad = degToRad(deg);
        const x   = Math.cos(rad) * RADIUS;
        const y   = -Math.sin(rad) * RADIUS; // negative = up
        
        const isActive = page === item.id;
        const isPulsing = activePulses[item.id];

        return (
          <button
            key={item.id}
            type="button"
            className={`ring-node ${isActive ? "active" : ""} ${isPulsing ? "pulse" : ""}`}
            style={{
              "--tx": `${x}px`,
              "--ty": `${y}px`,
              transitionDelay: open ? `${i * 30}ms` : `${(ITEMS.length - 1 - i) * 20}ms`,
            }}
            onClick={() => { setPage(item.id); setOpen(false); }}
            aria-label={item.label}
          >
            <span style={{ fontSize: "1.1rem", pointerEvents: "none" }}>{item.icon}</span>
            <span className="ring-node-label">{item.label}</span>
          </button>
        );
      })}

      <button
        type="button"
        className="ring-trigger"
        onClick={() => setOpen((v) => !v)}
      >
        <span style={{ fontSize: "1.4rem" }}>{open ? "✕" : "⬡"}</span>
        <div className={`ring-status-dot ${systemStatus}`} title={`System Status: ${systemStatus}`}></div>
      </button>
    </div>
  );
}
