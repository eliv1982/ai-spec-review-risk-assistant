import { NavLink } from "react-router-dom";

const NAV_LINKS: Array<{ to: string; label: string; end?: boolean }> = [
  { to: "/", label: "Проверить документ", end: true },
  { to: "/reviews", label: "История проверок" },
  { to: "/audit", label: "Журнал аудита" },
];

/** App-wide navigation. `NavLink` sets `aria-current="page"` on the active
 * link automatically, so screen readers and `:focus-visible` styling both
 * work without extra wiring. */
export function NavBar() {
  return (
    <header className="app-header">
      <nav className="nav" aria-label="Основная навигация">
        <ul className="nav-list">
          {NAV_LINKS.map((link) => (
            <li key={link.to}>
              <NavLink
                to={link.to}
                end={link.end}
                className={({ isActive }) => `nav-link${isActive ? " nav-link-active" : ""}`}
              >
                {link.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
