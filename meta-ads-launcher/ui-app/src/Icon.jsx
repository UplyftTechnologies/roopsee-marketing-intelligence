const P = {
  plus: 'M12 5v14M5 12h14',
  overview: 'M4 5h7v7H4zM13 5h7v4h-7zM13 11h7v8h-7zM4 14h7v5H4z',
  image: 'M4 5h16v14H4zM4 15l4-4 4 4 3-3 5 5M9 9.5h.01',
  setup: 'M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M6 14v6',
  run: 'M7 5l12 7-12 7z',
  health: 'M12 20s-7-4.5-7-10a4 4 0 017-2.5A4 4 0 0119 10c0 5.5-7 10-7 10z',
  chevron: 'M6 9l6 6 6-6',
  right: 'M9 6l6 6-6 6',
  left: 'M15 6l-6 6 6 6',
  menu: 'M4 7h16M4 12h16M4 17h16',
  info: 'M12 11v5M12 8h.01M12 3a9 9 0 100 18 9 9 0 000-18z',
  external: 'M14 4h6v6M20 4l-9 9M18 14v5H5V6h5',
  check: 'M5 12l5 5 9-10',
  refresh: 'M20 12a8 8 0 10-2.3 5.7M20 5v5h-5',
  trash: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13',
  copy: 'M9 9h10v11H9zM5 15V4h10',
}

export default function Icon({ name, size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={P[name] || P.info} />
    </svg>
  )
}
