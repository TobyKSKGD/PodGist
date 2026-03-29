interface LogoProps {
  size?: number;
}

export default function Logo({ size = 40 }: LogoProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 400 250"
      width={size}
      height={size * 0.625}
    >
      <defs>
        <linearGradient id="gradP" x1="0%" y1="100%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#001A9C" />
          <stop offset="100%" stopColor="#008080" />
        </linearGradient>
        <linearGradient id="gradG" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#00E5FF" />
          <stop offset="100%" stopColor="#B2FF59" />
        </linearGradient>
        <filter id="neonGlow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <filter id="super-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="6" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <g transform="translate(0, -10)" filter="url(#neonGlow)">
        <path
          d="M 120 190 L 120 60 L 160 60 A 50 50 0 0 1 160 160 L 120 160"
          fill="none"
          stroke="url(#gradP)"
          strokeWidth="32"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M 230 110 L 280 110 A 50 50 0 1 1 260 70"
          fill="none"
          stroke="url(#gradG)"
          strokeWidth="32"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="260" cy="70" r="14" fill="#FFFFFF" filter="url(#super-glow)" />
      </g>
    </svg>
  );
}
