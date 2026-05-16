import { useState, useRef, useEffect, useCallback } from "react";

/*
  Radial menu — hovers open from a fixed trigger button in the bottom-left.
  Items fan out in a quarter-circle arc (top-right quadrant).
  Clicking an item navigates and closes the menu.
*/

const ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: "⌂" },
  { id: "projects",  label: "Projects",  icon: "◫" },
  { id: "logs",      label: "Logs",      icon: "≡" },
  { id: "settings",  label: "Settings",  icon: "⚙" },
];

// Fan from 90° (straight up) to 0° (straight right), quarter-circle
const START_DEG = 92;
const END_DEG   = 8;
const RADIUS    = 96; // px from trigger centre to item centre

function degToRad(d) { return (d * Math.PI) / 180; }

export default function RadialNav({ page, setPage, theme, setTheme }) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);
  const closeTimer = useRef(null);

  const openMenu  = useCallback(() => { clearTimeout(closeTimer.current); setOpen(true);  }, []);
  const closeMenu = useCallback(() => { closeTimer.current = setTimeout(() => setOpen(false), 180); }, []);

  // Close on outside click
  useEffect(() => {
    function onDown(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  // Close on Escape
  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const step = (END_DEG - START_DEG) / (ITEMS.length - 1);

  return (
    <div
      ref={menuRef}
      className="radial-nav"
      onMouseEnter={openMenu}
      onMouseLeave={closeMenu}
      aria-label="Main navigation"
    >
      {/* Fan items */}
      {ITEMS.map((item, i) => {
        const deg = START_DEG + step * i;
        const rad = degToRad(deg);
        const x   = Math.cos(rad) * RADIUS;
        const y   = -Math.sin(rad) * RADIUS; // negative = upward in CSS
        const isActive = page === item.id;

        return (
          <button
            key={item.id}
            type="button"
            className={`radial-item ${isActive ? "active" : ""} ${open ? "visible" : ""}`}
            style={{
              "--tx": `${x}px`,
              "--ty": `${y}px`,
              transitionDelay: open ? `${i * 40}ms` : `${(ITEMS.length - 1 - i) * 30}ms`,
            }}
            onClick={() => { setPage(item.id); setOpen(false); }}
            aria-label={item.label}
            aria-current={isActive ? "page" : undefined}
          >
            <span className="radial-item-icon" aria-hidden="true">{item.icon}</span>
            <span className="radial-item-label">{item.label}</span>
          </button>
        );
      })}

      {/* Trigger button */}
      <button
        type="button"
        className={`radial-trigger ${open ? "open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-label="Open navigation"
        aria-expanded={open}
      >
        <span className="radial-trigger-icon" aria-hidden="true">
          {open ? "✕" : "⬡"}
        </span>
        <span className="radial-trigger-label">
          {ITEMS.find((i) => i.id === page)?.label ?? "Menu"}
        </span>
      </button>

      {/* Theme toggle — sits just above the trigger */}
      <button
        type="button"
        className="radial-theme-toggle"
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        aria-label="Toggle theme"
        title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      >
        {theme === "dark" ? "☀" : "☾"}
      </button>
    </div>
  );
}
