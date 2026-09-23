type LogoProps = {
  className?: string;
};

/** App mark: a magnifier over a rising price line ending in an amber alert blip. Mirrors public/favicon.svg. */
export function Logo({ className }: LogoProps) {
  return (
    <svg className={className} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="#121214" />
      <path d="M44 44l13.2 13.2" stroke="#d4d4d8" strokeWidth="7.4" strokeLinecap="round" />
      <circle cx="25.6" cy="25.6" r="23.7" stroke="#d4d4d8" strokeWidth="3.8" />
      <path
        d="M9.5 33.6l8-8 6.9 6.9 11.5-15"
        stroke="#10b981"
        strokeWidth="6.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="35.9" cy="17.5" r="5.75" fill="#f59e0b" />
    </svg>
  );
}
