// Small stroke icon set (24x24 grid). Paths are simple geometry, so no icon library is needed.
const P = {
  home: 'M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
  tag: 'M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9-9-9zM7.5 7.5h.01',
  route: 'M6 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 17V9.5A3.5 3.5 0 0 1 9.5 6H16M18 7v7.5a3.5 3.5 0 0 1-3.5 3.5H8',
  alert: 'M12 3.5 2.5 20h19zM12 10v4.5M12 17.2h.01',
  map: 'M9 4 3 6.5V20l6-2.5 6 2.5 6-2.5V4l-6 2.5L9 4zM9 4v13.5M15 6.5V20',
  image: 'M4 5h16v14H4zM4 15.5l4.5-4.5 4 4 2.5-2.5 5 5M15.5 9.2h.01',
  pulse: 'M3 12h4l2.5-6 5 12 2.5-6h4',
  login: 'M14 4h5a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-5M9.5 16l4-4-4-4M13.5 12H3',
  chat: 'M4 5h16v11H10l-6 4.5z',
  book: 'M5 5.5A2.5 2.5 0 0 1 7.5 3H19v15H7.5A2.5 2.5 0 0 0 5 20.5zM5 20.5A2.5 2.5 0 0 0 7.5 21H19',
  sliders: 'M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1M15 4v4M9 10v4M17 16v4',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  funnel: 'M3 4h18l-7 8.5V19l-4 2v-8.5z',
  megaphone: 'M3 10v4a1 1 0 0 0 1 1h2l8 4V5L6 9H4a1 1 0 0 0-1 1zM18 8.5a4.5 4.5 0 0 1 0 7',
  globe: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3.2 3 3.2 15 0 18M12 3c-3.2 3-3.2 15 0 18',
  basket: 'M4 9h16l-1.6 10.2a1 1 0 0 1-1 .8H6.6a1 1 0 0 1-1-.8zM8.5 9 12 4l3.5 5',
  loop: 'M20 12a8 8 0 1 1-2.6-5.9M20 4v5h-5',
  target: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM12 11.2a.8.8 0 1 0 0 1.6.8.8 0 0 0 0-1.6z',
  list: 'M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01',
  users: 'M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 18.5V20M10 12a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM20 20v-1.5a3.5 3.5 0 0 0-2.6-3.4M15.5 5.2a3.5 3.5 0 0 1 0 6.6',
  ban: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM5.6 5.6l12.8 12.8',
  database: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  calendar: 'M4 6h16v14H4zM4 10.5h16M8.5 3.5v4M15.5 3.5v4',
  chevron: 'M6 9l6 6 6-6',
  left: 'M15 6l-6 6 6 6',
  right: 'M9 6l6 6-6 6',
  menu: 'M4 7h16M4 12h16M4 17h16',
  refresh: 'M20 12a8 8 0 1 1-2.6-5.9M20 4v5h-5',
  shield: 'M12 3l8 3v6c0 4.8-3.3 8-8 9-4.7-1-8-4.2-8-9V6z',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v5M12 7.8v.01',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4',
  receipt: 'M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6M9 16h3',
  trend: 'M3 17l6-6 4 4 8-8M15 7h6v6',
  copy: 'M9 9h11v11H9zM5 15V4h11',
  close: 'M6 6l12 12M18 6 6 18',
}

export default function Icon({ name, size = 20, ...rest }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...rest}>
      <path d={P[name] || P.info} />
    </svg>
  )
}
