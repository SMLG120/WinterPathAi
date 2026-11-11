/** Original WinterPath mark: a path line through a six-point frost star. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="8" fill="#101B2C" />
      <g stroke="#BDE8F4" strokeWidth="1.6" strokeLinecap="round">
        <path d="M16 6v20M7.3 11l17.4 10M7.3 21l17.4-10" />
      </g>
      <path d="M6 26c5-1 7-5 10-10s5-8 10-9" fill="none" stroke="#087F8C" strokeWidth="3" strokeLinecap="round" />
      <circle cx="26" cy="7" r="2" fill="#E7A83E" />
    </svg>
  );
}
