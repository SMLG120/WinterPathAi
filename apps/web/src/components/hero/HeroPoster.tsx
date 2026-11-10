/**
 * Static poster (original SVG illustration). Shown first for LCP, and as the
 * permanent fallback for reduced motion / no WebGL. Decorative (aria-hidden).
 */
export function HeroPoster({ className }: { className?: string }) {
  const houses = [
    { x: 20, w: 120, h: 190, c: '#8c4a3c' },
    { x: 140, w: 110, h: 210, c: '#9b5b45' },
    { x: 250, w: 125, h: 180, c: '#7a4436' },
    { x: 375, w: 115, h: 200, c: '#a8705a' },
    { x: 490, w: 120, h: 185, c: '#6f5b52' },
  ];
  return (
    <svg viewBox="0 0 640 400" preserveAspectRatio="xMidYMid slice" className={className} aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#0b1422" />
          <stop offset="1" stopColor="#1d3149" />
        </linearGradient>
        <radialGradient id="glow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#ffd27a" stopOpacity="0.55" />
          <stop offset="1" stopColor="#ffd27a" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="640" height="400" fill="url(#sky)" />
      {houses.map((h, i) => (
        <g key={i}>
          <rect x={h.x} y={300 - h.h} width={h.w} height={h.h} fill={h.c} />
          <rect x={h.x - 4} y={292 - h.h} width={h.w + 8} height={10} fill="#eef4f8" />
          {[0, 1, 2].map((f) =>
            [0.25, 0.65].map((fx) => (
              <rect key={`${f}-${fx}`} x={h.x + h.w * fx} y={300 - h.h + 26 + f * 56} width={22} height={30} fill="#f6d8a0" opacity="0.9" />
            )),
          )}
          {/* exterior staircase */}
          <path d={`M${h.x + 10} 300 L${h.x + 48} ${300 - h.h / 2.6}`} stroke="#2b2f36" strokeWidth="5" />
          {[0, 1, 2, 3, 4, 5].map((s) => (
            <rect key={s} x={h.x + 12 + s * 6} y={296 - s * ((h.h / 2.6) / 6)} width={12} height={3} fill="#2b2f36" />
          ))}
          <rect x={h.x + 40} y={300 - h.h / 2.6 - 4} width={h.w - 50} height={5} fill="#2b2f36" />
        </g>
      ))}
      {/* sidewalk, snowbanks, road */}
      <rect y="300" width="640" height="22" fill="#dfe9f0" />
      <rect y="322" width="640" height="78" fill="#4a5566" />
      {Array.from({ length: 12 }, (_, i) => (
        <ellipse key={i} cx={20 + i * 56} cy="322" rx="30" ry="11" fill="#f7fafc" />
      ))}
      {/* streetlights */}
      {[110, 330, 550].map((x) => (
        <g key={x}>
          <circle cx={x} cy="178" r="40" fill="url(#glow)" />
          <rect x={x - 2} y="180" width="4" height="122" fill="#1d2633" />
          <circle cx={x} cy="178" r="6" fill="#fff4d6" />
        </g>
      ))}
      {/* highlighted path */}
      <path d="M0 311 H420 Q450 311 455 340 L470 400" fill="none" stroke="#087f8c" strokeWidth="5" strokeDasharray="14 9" strokeLinecap="round" />
      {/* pedestrian */}
      <g transform="translate(300 268)">
        <rect x="-6" y="8" width="12" height="26" rx="6" fill="#087f8c" />
        <circle cx="0" cy="2" r="6" fill="#f0c9a8" />
        <path d="M-7 -2 L0 -12 L7 -2 Z" fill="#e7a83e" />
      </g>
      {/* snowfall */}
      {Array.from({ length: 70 }, (_, i) => (
        <circle key={i} cx={(i * 97) % 640} cy={(i * 53) % 290} r={(i % 3) + 1} fill="#f7fafc" opacity="0.8" />
      ))}
    </svg>
  );
}
