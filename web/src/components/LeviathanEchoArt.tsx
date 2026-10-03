/**
 * Иероглифическая архивная иллюстрация:
 * Левиафан с экипажем Кормчих внутри, Резонирующий Монолит в эпицентре волн эха
 * и поселение людей у подножия. Все выноски и гравировки выполнены на аутентичном
 * выдуманном языке Кормчих (астролябии, глифы и звёздные руны).
 */
import { useSession } from "../stores/session";

export default function LeviathanEchoArt({
  className,
  mode: propMode,
}: {
  className?: string;
  mode?: "dark" | "light";
}) {
  const sessionMode = useSession((s) => s.mode);
  const isLight = (propMode ?? sessionMode) === "light";

  const cDark = {
    darkFill1: "#111215",
    darkFill2: "#121317",
    darkFill3: "#141519",
    darkFill4: "#14161a",
    darkFill5: "#15171b",
    darkFill6: "#16181d",
    darkFill7: "#17181c",
    darkLine1: "#1c1e24",
    darkLine2: "#22242a",
    darkLine3: "#24252a",
    patina1: "#5fae9f",
    patina2: "#7fc2b4",
    copper1: "#c98a4b",
    copper2: "#d59a5c",
    ink: "#ece6dc",
    muted: "#a8a296",
  };

  const cLight = {
    darkFill1: "#cbbfac",
    darkFill2: "#ded5c6",
    darkFill3: "#ded4c5",
    darkFill4: "#eae1d2",
    darkFill5: "#ede3d4",
    darkFill6: "#e5dccf",
    darkFill7: "#d9cfbe",
    darkLine1: "#d8d1c4",
    darkLine2: "#b0a492",
    darkLine3: "#b0a492",
    patina1: "#267364",
    patina2: "#1b5e53",
    copper1: "#8a5a1c",
    copper2: "#6e4614",
    ink: "#2c241c",
    muted: "#6b5d4f",
  };

  const c = isLight ? cLight : cDark;

  return (
    <svg
      viewBox="0 0 1600 900"
      fill="none"
      aria-hidden="true"
      preserveAspectRatio="xMaxYMid slice"
      className={className ?? "pointer-events-none absolute inset-0 h-full w-full select-none opacity-85 overflow-hidden"}
      xmlns="http://www.w3.org/2000/svg"
    >
  <defs>
    <radialGradient id="crystalGlow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stopColor={c.patina1} stopOpacity="0.5" />
      <stop offset="45%" stopColor={c.patina1} stopOpacity="0.15" />
      <stop offset="100%" stopColor={c.patina1} stopOpacity="0" />
    </radialGradient>
    <radialGradient id="eyeGlow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stopColor={isLight ? "#d9822b" : "#f0b475"} stopOpacity="0.95" />
      <stop offset="50%" stopColor={c.copper2} stopOpacity="0.45" />
      <stop offset="100%" stopColor={c.copper1} stopOpacity="0" />
    </radialGradient>
    <linearGradient id="leviathanHull" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stopColor={c.copper1} stopOpacity="0.2" />
      <stop offset="45%" stopColor={c.copper1} stopOpacity="0.08" />
      <stop offset="100%" stopColor={c.copper2} stopOpacity="0.25" />
    </linearGradient>
    <linearGradient id="crystalFacetA" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stopColor={c.patina2} stopOpacity="0.5" />
      <stop offset="100%" stopColor={c.darkFill7} stopOpacity="0.85" />
    </linearGradient>
    <linearGradient id="crystalFacetB" x1="100%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stopColor={c.patina1} stopOpacity="0.4" />
      <stop offset="100%" stopColor={c.darkFill1} stopOpacity="0.95" />
    </linearGradient>
  </defs>

  {/* 1. Фоновая сетка чертежа и координаты */}
  <g stroke={c.darkLine1} strokeWidth="1">
    <line x1="0" y1="110" x2="1600" y2="110" strokeDasharray="4 8" opacity="0.5" />
    <line x1="0" y1="780" x2="1600" y2="780" strokeDasharray="4 8" opacity="0.5" />
    <line x1="160" y1="0" x2="160" y2="900" strokeDasharray="4 8" opacity="0.4" />
    <line x1="1440" y1="0" x2="1440" y2="900" strokeDasharray="4 8" opacity="0.4" />
  </g>

  {/* Горизонт земли и водной глади */}
  <g>
    <line x1="40" y1="720" x2="1560" y2="720" stroke={c.ink} strokeOpacity="0.18" strokeWidth="1.2" />
    <line x1="40" y1="728" x2="1560" y2="728" stroke={c.ink} strokeOpacity="0.08" strokeDasharray="3 7" strokeWidth="1" />
    <line x1="40" y1="738" x2="1560" y2="738" stroke={c.ink} strokeOpacity="0.04" strokeWidth="1" />
    <path d="M 60 720 Q 200 715 350 720 T 700 720 T 1000 720 Q 1040 712 1080 720 T 1200 720 Q 1350 714 1540 720"
          fill="none" stroke={c.darkLine3} strokeWidth="1.5" />
  </g>

  {/* 2. Волны Эха (Concentric Echo Rings) вокруг кристалла/скалы (фокус: 1180, 440) */}
  <g id="echo-waves" stroke={c.patina1} fill="none">
    <circle cx="1180" cy="440" r="160" fill="url(#crystalGlow)" stroke="none" />
    
    <circle cx="1180" cy="440" r="55" strokeOpacity="0.6" strokeWidth="1.2" />
    <circle cx="1180" cy="440" r="105" strokeOpacity="0.35" strokeWidth="1" strokeDasharray="4 6" />
    <circle cx="1180" cy="440" r="165" strokeOpacity="0.45" strokeWidth="1" />
    <circle cx="1180" cy="440" r="235" strokeOpacity="0.28" strokeWidth="1" strokeDasharray="6 8" />
    <circle cx="1180" cy="440" r="315" strokeOpacity="0.38" strokeWidth="1.2" />
    <circle cx="1180" cy="440" r="415" strokeOpacity="0.22" strokeWidth="1" strokeDasharray="4 10" />
    <circle cx="1180" cy="440" r="530" strokeOpacity="0.26" strokeWidth="1" />
    <circle cx="1180" cy="440" r="665" strokeOpacity="0.16" strokeWidth="1" strokeDasharray="8 12" />
    <circle cx="1180" cy="440" r="820" strokeOpacity="0.14" strokeWidth="1" />
    <circle cx="1180" cy="440" r="1000" strokeOpacity="0.09" strokeWidth="1" strokeDasharray="6 14" />
    <circle cx="1180" cy="440" r="1200" strokeOpacity="0.06" strokeWidth="1" />

    <line x1="1180" y1="440" x2="380" y2="440" strokeOpacity="0.22" strokeDasharray="3 9" strokeWidth="1" />
    <line x1="1180" y1="440" x2="620" y2="200" strokeOpacity="0.18" strokeDasharray="3 9" strokeWidth="1" />
    <line x1="1180" y1="440" x2="740" y2="700" strokeOpacity="0.16" strokeDasharray="3 9" strokeWidth="1" />
    <line x1="1180" y1="440" x2="1520" y2="220" strokeOpacity="0.14" strokeDasharray="3 9" strokeWidth="1" />
  </g>

  {/* 3. Скала-Монолит и Минерал в центре волн */}
  <g id="monolith" strokeLinejoin="round">
    <polygon points="1105,720 1130,550 1160,420 1180,310 1200,410 1235,530 1270,720"
             fill={c.darkFill2} stroke={c.darkLine2} strokeWidth="1" />
    
    <polygon points="1180,310 1145,410 1175,465 1205,405"
             fill="url(#crystalFacetA)" stroke={c.patina2} strokeWidth="1.8" />
    <polygon points="1180,310 1175,465 1182,530 1205,405"
             fill="url(#crystalFacetB)" stroke={c.patina1} strokeWidth="1.5" />
    <polygon points="1145,410 1125,505 1165,540 1175,465"
             fill={c.darkFill6} stroke={c.patina1} strokeWidth="1.2" strokeOpacity="0.85" />
    <polygon points="1205,405 1175,465 1185,550 1230,490"
             fill={c.darkFill3} stroke={c.patina1} strokeWidth="1.2" strokeOpacity="0.85" />

    <line x1="1180" y1="310" x2="1175" y2="465" stroke={c.ink} strokeWidth="1.4" strokeOpacity="0.7" />
    <line x1="1145" y1="410" x2="1205" y2="405" stroke={c.patina1} strokeWidth="1" strokeOpacity="0.5" />
    
    <path d="M1105 720 L1120 620 L1145 550 L1165 540 L1185 550 L1215 580 L1240 640 L1270 720"
          fill="none" stroke={c.copper1} strokeOpacity="0.65" strokeWidth="1.4" />
    <line x1="1145" y1="550" x2="1135" y2="720" stroke={c.copper1} strokeOpacity="0.3" strokeWidth="1" />
    <line x1="1185" y1="550" x2="1190" y2="720" stroke={c.copper1} strokeOpacity="0.3" strokeWidth="1" />
    <line x1="1215" y1="580" x2="1225" y2="720" stroke={c.copper1} strokeOpacity="0.3" strokeWidth="1" />
    
    <circle cx="1177" cy="425" r="5" fill={c.patina2} />
    <circle cx="1177" cy="425" r="14" stroke={c.patina2} strokeWidth="1.2" strokeDasharray="3 3" fill="none" opacity="0.6" />
    <line x1="1177" y1="300" x2="1177" y2="150" stroke={c.patina1} strokeWidth="1" strokeDasharray="4 8" strokeOpacity="0.4" />

    {/* Рунические письмена на самом кристалле */}
    <g transform="translate(1177, 360) scale(0.7)" color={c.ink}>
<g transform="translate(0, 0)"><path d="M 0,-11 L 0,11 M -6,-3 L 0,-9 L 6,-3 M -4,4 L 0,8 L 4,4" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="-11" r="1.5" fill="currentColor"/></g>
<g transform="translate(0, 28)"><polygon points="0,-11 7,0 0,11 -7,0" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1"/>
       <circle cx="0" cy="0" r="2" fill="currentColor"/></g>
<g transform="translate(0, 56)"><path d="M -9,0 Q 0,-8 9,0 Q 0,8 -9,0 Z" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="0" r="3" fill="currentColor"/>
       <line x1="0" y1="-11" x2="0" y2="-6" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="6" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/></g>
<g transform="translate(0, 84)"><circle cx="0" cy="-4" r="5" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <path d="M 0,1 L 0,11 M -7,8 L 0,11 L 7,8" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="-4" r="1.5" fill="currentColor"/></g>
</g>
  </g>

  {/* 4. Деревушка людей около скалы */}
  <g id="village">
    <path d="M 1072 675 Q 1068 660 1074 650 T 1070 635" fill="none" stroke={c.ink} strokeWidth="1" strokeOpacity="0.35" strokeLinecap="round" />
    <path d="M 1272 680 Q 1276 665 1270 652 T 1274 640" fill="none" stroke={c.ink} strokeWidth="1" strokeOpacity="0.3" strokeLinecap="round" />

    {/* Дома деревушки */}
    <path d="M 1055 720 L 1055 692 L 1075 672 L 1095 692 L 1095 720 Z" fill={c.darkFill4} stroke={c.copper1} strokeWidth="1.3" />
    <line x1="1075" y1="672" x2="1075" y2="720" stroke={c.copper1} strokeOpacity="0.4" strokeWidth="1" />
    <rect x="1071" y="670" width="3" height="6" fill={c.darkFill4} stroke={c.copper1} strokeWidth="1" />
    <rect x="1068" y="698" width="6" height="8" fill="#d9b44a" opacity="0.85" />

    <path d="M 1098 720 L 1098 698 L 1116 682 L 1132 698 L 1132 720 Z" fill={c.darkFill6} stroke={c.ink} strokeOpacity="0.75" strokeWidth="1.2" />
    <rect x="1112" y="702" width="6" height="8" fill="#d9b44a" opacity="0.9" />

    <path d="M 1248 720 L 1248 694 L 1268 676 L 1288 694 L 1288 720 Z" fill={c.darkFill4} stroke={c.copper1} strokeWidth="1.3" />
    <rect x="1264" y="674" width="3" height="6" fill={c.darkFill4} stroke={c.copper1} strokeWidth="1" />
    <rect x="1262" y="700" width="6" height="8" fill="#d9b44a" opacity="0.85" />

    <path d="M 1296 720 L 1296 702 L 1312 688 L 1328 702 L 1328 720 Z" fill={c.darkFill6} stroke={c.ink} strokeOpacity="0.6" strokeWidth="1" />

    {/* Смотровая вышка */}
    <path d="M 1030 720 L 1036 655 L 1048 655 L 1054 720" fill="none" stroke={c.copper1} strokeWidth="1.3" />
    <line x1="1032" y1="690" x2="1052" y2="690" stroke={c.copper1} strokeWidth="1" />
    <line x1="1034" y1="670" x2="1050" y2="670" stroke={c.copper1} strokeWidth="1" />
    <circle cx="1042" cy="650" r="5" fill="#d9b44a" />
    <circle cx="1042" cy="650" r="14" stroke="#d9b44a" strokeWidth="0.8" strokeDasharray="2 3" fill="none" opacity="0.5" />

    {/* Силуэты людей в деревне */}
    <g transform="translate(1042, 642)" fill={c.ink}>
      <circle cx="0" cy="-6" r="1.8" />
      <line x1="0" y1="-4" x2="0" y2="2" stroke={c.ink} strokeWidth="1.4" />
      <line x1="0" y1="-2" x2="-3.5" y2="0" stroke={c.ink} strokeWidth="1.2" />
      <line x1="0" y1="2" x2="-1.5" y2="6" stroke={c.ink} strokeWidth="1.2" />
      <line x1="0" y1="2" x2="1.5" y2="6" stroke={c.ink} strokeWidth="1.2" />
    </g>

    <g transform="translate(1082, 715)" fill={c.ink}>
      <circle cx="0" cy="-14" r="2.2" />
      <line x1="0" y1="-12" x2="0" y2="-4" stroke={c.ink} strokeWidth="1.6" />
      <line x1="0" y1="-9" x2="-5" y2="-13" stroke={c.ink} strokeWidth="1.2" />
      <line x1="0" y1="-4" x2="-2" y2="0" stroke={c.ink} strokeWidth="1.4" />
      <line x1="0" y1="-4" x2="2" y2="0" stroke={c.ink} strokeWidth="1.4" />
    </g>

    <g transform="translate(1092, 715)" fill={c.ink}>
      <circle cx="0" cy="-15" r="2.2" />
      <line x1="0" y1="-13" x2="0" y2="-4" stroke={c.ink} strokeWidth="1.6" />
      <line x1="-3" y1="-18" x2="-3" y2="0" stroke={c.copper1} strokeWidth="1.2" />
      <line x1="0" y1="-10" x2="-3" y2="-10" stroke={c.ink} strokeWidth="1.2" />
      <line x1="0" y1="-4" x2="-2" y2="0" stroke={c.ink} strokeWidth="1.4" />
      <line x1="0" y1="-4" x2="2" y2="0" stroke={c.ink} strokeWidth="1.4" />
    </g>

    <g transform="translate(1155, 715)" fill={c.ink}>
      <circle cx="0" cy="-14" r="2.2" />
      <line x1="0" y1="-12" x2="0" y2="-4" stroke={c.ink} strokeWidth="1.6" />
      <line x1="0" y1="-9" x2="4" y2="-13" stroke={c.ink} strokeWidth="1.2" />
      <line x1="0" y1="-4" x2="-2" y2="0" stroke={c.ink} strokeWidth="1.4" />
      <line x1="0" y1="-4" x2="2" y2="0" stroke={c.ink} strokeWidth="1.4" />
    </g>

    <g transform="translate(1238, 715)" fill={c.ink}>
      <circle cx="0" cy="-14" r="2" />
      <line x1="0" y1="-12" x2="0" y2="-4" stroke={c.ink} strokeWidth="1.5" />
      <line x1="0" y1="-4" x2="-2" y2="0" stroke={c.ink} strokeWidth="1.3" />
      <line x1="0" y1="-4" x2="2" y2="0" stroke={c.ink} strokeWidth="1.3" />
    </g>
    <g transform="translate(1246, 715)" fill={c.ink}>
      <circle cx="0" cy="-11" r="1.8" />
      <line x1="0" y1="-9" x2="0" y2="-3" stroke={c.ink} strokeWidth="1.4" />
      <line x1="0" y1="-3" x2="-1.5" y2="0" stroke={c.ink} strokeWidth="1.2" />
      <line x1="0" y1="-3" x2="1.5" y2="0" stroke={c.ink} strokeWidth="1.2" />
    </g>
  </g>

  {/* 5. ЛЕВИАФАН (Величественный кит глубин и эфира) */}
  <g id="leviathan">
    <path d="M140 500 C 290 380, 520 340, 740 370 C 850 385, 930 435, 970 495 C 930 520, 840 510, 720 500 C 510 490, 310 520, 140 500 Z"
          fill="url(#leviathanHull)" />

    {/* Верхний контур спины */}
    <path d="M140 500 C 290 380, 520 340, 740 370 C 850 385, 930 435, 970 495"
          fill="none" stroke={c.copper2} strokeWidth="2.4" strokeLinecap="round" />
    {/* Нижний контур брюха */}
    <path d="M170 524 C 320 500, 540 500, 720 485 C 840 475, 915 500, 955 515"
          fill="none" stroke={c.copper1} strokeWidth="2" strokeLinecap="round" />

    {/* Грудной плавник левиафана */}
    <path d="M 680 488 C 650 540, 590 570, 540 580 C 570 555, 620 515, 650 490"
          fill={c.darkFill4} stroke={c.copper1} strokeWidth="1.8" />
    <path d="M 640 505 L 565 565 M 655 498 L 595 550" stroke={c.copper1} strokeOpacity="0.4" strokeWidth="1" />

    {/* Голова и морда левиафана */}
    <ellipse cx="890" cy="460" rx="65" ry="38" fill="none" stroke={c.copper1} strokeWidth="1.8" />
    <path d="M940 450 C 975 460, 990 480, 960 510" fill="none" stroke={c.copper2} strokeWidth="2" />
    <path d="M920 495 L 970 495" stroke={c.copper1} strokeWidth="1.4" />

    {/* Глаз-линза левиафана */}
    <circle cx="910" cy="450" r="20" fill="url(#eyeGlow)" />
    <circle cx="910" cy="450" r="9" fill="none" stroke={c.copper2} strokeWidth="1.8" />
    <circle cx="910" cy="450" r="3.5" fill={c.ink} />

    {/* Хвостовое оперение */}
    <path d="M140 500 L 70 540 L 120 520 L 85 580 L 155 522 Z" fill={c.darkFill5} stroke={c.copper1} strokeWidth="2" />
    <path d="M110 525 L 75 555 M 105 530 L 88 570" stroke={c.copper1} strokeWidth="1" strokeOpacity="0.6" />

    {/* Сегментированные РЁБРА левиафана */}
    <g stroke={c.copper1} strokeWidth="1.6" fill="none" strokeLinecap="round">
      <path d="M250 445 Q 235 485 255 516" />
      <path d="M305 424 Q 288 472 310 514" />
      <path d="M365 407 Q 344 462 370 510" />
      <path d="M428 393 Q 403 454 433 506" />
      <path d="M492 384 Q 464 448 497 501" />
      <path d="M558 378 Q 530 445 562 497" />
      <path d="M625 375 Q 598 442 628 492" />
      <path d="M692 376 Q 668 440 695 488" />
      <path d="M758 382 Q 738 438 762 485" />
      <path d="M820 395 Q 804 440 824 480" />
    </g>

    {/* Иероглифические письмена Кормчих вдоль корпуса кита */}
    <g transform="translate(430, 460) scale(0.6)" color={c.copper1}>
<g transform="translate(0, 0)"><path d="M -7,-7 L 0,-1 L 7,-7 M -7,3 L 0,9 L 7,3" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-11" r="1.3" fill="currentColor"/></g>
<g transform="translate(35, 0)"><path d="M -8,-8 Q -4,0 -8,8 M -2,-10 Q 3,0 -2,10 M 4,-6 Q 8,0 4,6" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="8" cy="-8" r="1.3" fill="currentColor"/>
       <circle cx="8" cy="8" r="1.3" fill="currentColor"/></g>
<g transform="translate(70, 0)"><circle cx="0" cy="0" r="7" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="-9" y1="0" x2="9" y2="0" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="0" cy="-7" r="1.2" fill="currentColor"/>
       <circle cx="0" cy="7" r="1.2" fill="currentColor"/></g>
<g transform="translate(105, 0)"><path d="M 5,-10 A 11 11 0 0 0 5,10 M -4,-5 L 4,-5 M -6,0 L 2,0 M -4,5 L 4,5" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="-2" cy="-10" r="1.2" fill="currentColor"/></g>
<g transform="translate(140, 0)"><line x1="-8" y1="-8" x2="8" y2="-8" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="8" x2="8" y2="8" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-4" y1="-8" x2="4" y2="8" stroke="currentColor" strokeWidth="1.1"/>
       <line x1="4" y1="-8" x2="-4" y2="8" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="0" r="1.8" fill="currentColor"/></g>
</g>

    {/* Палубы и мостики внутри каркаса */}
    <line x1="260" y1="482" x2="850" y2="465" stroke={c.patina1} strokeOpacity="0.75" strokeWidth="1.4" />
    <line x1="380" y1="435" x2="800" y2="425" stroke={c.patina1} strokeOpacity="0.45" strokeDasharray="4 3" strokeWidth="1" />
    
    <g stroke={c.patina1} strokeOpacity="0.55" strokeWidth="1">
      <line x1="430" y1="435" x2="430" y2="480" />
      <line x1="560" y1="430" x2="560" y2="475" />
      <line x1="690" y1="428" x2="690" y2="472" />
      <line x1="557" y1="440" x2="563" y2="440" />
      <line x1="557" y1="450" x2="563" y2="450" />
      <line x1="557" y1="460" x2="563" y2="460" />
    </g>

    {/* Сердце левиафана */}
    <ellipse cx="630" cy="455" rx="7" ry="12" fill={c.patina1} fillOpacity="0.35" stroke={c.patina2} strokeWidth="1.2" />
    <circle cx="630" cy="455" r="3.5" fill={c.copper2} />
    <line x1="620" y1="455" x2="640" y2="455" stroke={c.patina2} strokeWidth="1" strokeDasharray="2 2" />

    {/* Фигурки Кормчих */}
    <g transform="translate(855, 465)" fill={c.copper2}>
      <circle cx="0" cy="-14" r="2.2" />
      <line x1="0" y1="-12" x2="0" y2="-4" stroke={c.copper2} strokeWidth="1.6" />
      <line x1="0" y1="-9" x2="4" y2="-7" stroke={c.copper2} strokeWidth="1.2" />
      <line x1="0" y1="-4" x2="-2" y2="0" stroke={c.copper2} strokeWidth="1.4" />
      <line x1="0" y1="-4" x2="2" y2="0" stroke={c.copper2} strokeWidth="1.4" />
      <rect x="5" y="-11" width="3.5" height="11" fill={c.patina1} opacity="0.85" />
    </g>

    <g transform="translate(740, 426)" fill={c.ink}>
      <circle cx="0" cy="-12" r="2" />
      <line x1="0" y1="-10" x2="0" y2="-3" stroke={c.ink} strokeWidth="1.5" />
      <line x1="0" y1="-8" x2="4" y2="-12" stroke={c.ink} strokeWidth="1.1" />
      <line x1="0" y1="-3" x2="-1.5" y2="0" stroke={c.ink} strokeWidth="1.3" />
      <line x1="0" y1="-3" x2="1.5" y2="0" stroke={c.ink} strokeWidth="1.3" />
    </g>

    <g transform="translate(615, 474)" fill={c.ink}>
      <circle cx="0" cy="-13" r="2.1" />
      <line x1="0" y1="-11" x2="0" y2="-4" stroke={c.ink} strokeWidth="1.5" />
      <line x1="0" y1="-8" x2="-4" y2="-5" stroke={c.ink} strokeWidth="1.2" />
      <line x1="0" y1="-4" x2="-2" y2="0" stroke={c.ink} strokeWidth="1.3" />
      <line x1="0" y1="-4" x2="2" y2="0" stroke={c.ink} strokeWidth="1.3" />
    </g>

    <g transform="translate(485, 479)" fill={c.ink}>
      <circle cx="0" cy="-13" r="2" />
      <line x1="0" y1="-11" x2="0" y2="-4" stroke={c.ink} strokeWidth="1.5" />
      <line x1="0" y1="-8" x2="3" y2="-6" stroke={c.ink} strokeWidth="1.1" />
      <line x1="0" y1="-4" x2="-3" y2="0" stroke={c.ink} strokeWidth="1.3" />
      <line x1="0" y1="-4" x2="3" y2="0" stroke={c.ink} strokeWidth="1.3" />
    </g>

    <g transform="translate(350, 483)" fill={c.ink}>
      <circle cx="0" cy="-13" r="2" />
      <line x1="0" y1="-11" x2="0" y2="-4" stroke={c.ink} strokeWidth="1.5" />
      <line x1="-3" y1="-14" x2="-3" y2="-3" stroke="#d9b44a" strokeWidth="1.2" />
      <circle cx="-3" cy="-14" r="2.2" fill="#d9b44a" />
      <line x1="0" y1="-8" x2="-3" y2="-10" stroke={c.ink} strokeWidth="1.1" />
      <line x1="0" y1="-4" x2="-2" y2="0" stroke={c.ink} strokeWidth="1.3" />
      <line x1="0" y1="-4" x2="2" y2="0" stroke={c.ink} strokeWidth="1.3" />
    </g>
  </g>

  {/* 6. ИЕРОГЛИФИЧЕСКИЕ ВЫНОСКИ И НАДПИСИ НА ВЫДУМАННОМ ЯЗЫКЕ КОРМЧИХ */}
  {/* Заголовок карты */}
  <g transform="translate(70, 70) scale(1.1)" color={c.copper2}>
<g transform="translate(0, 0)"><circle cx="0" cy="0" r="7" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="-9" y1="0" x2="9" y2="0" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="0" cy="-7" r="1.2" fill="currentColor"/>
       <circle cx="0" cy="7" r="1.2" fill="currentColor"/></g>
<g transform="translate(26, 0)"><path d="M 0,-11 L 0,11 M -6,-3 L 0,-9 L 6,-3 M -4,4 L 0,8 L 4,4" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="-11" r="1.5" fill="currentColor"/></g>
<g transform="translate(52, 0)"><path d="M -9,0 Q 0,-8 9,0 Q 0,8 -9,0 Z" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="0" r="3" fill="currentColor"/>
       <line x1="0" y1="-11" x2="0" y2="-6" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="6" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/></g>
<g transform="translate(78, 0)"><polygon points="0,-11 7,0 0,11 -7,0" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1"/>
       <circle cx="0" cy="0" r="2" fill="currentColor"/></g>
<g transform="translate(104, 0)"><path d="M -8,-8 Q -4,0 -8,8 M -2,-10 Q 3,0 -2,10 M 4,-6 Q 8,0 4,6" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="8" cy="-8" r="1.3" fill="currentColor"/>
       <circle cx="8" cy="8" r="1.3" fill="currentColor"/></g>
<g transform="translate(130, 0)"><path d="M -7,-7 L 0,-1 L 7,-7 M -7,3 L 0,9 L 7,3" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-11" r="1.3" fill="currentColor"/></g>
<g transform="translate(156, 0)"><circle cx="0" cy="-4" r="5" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <path d="M 0,1 L 0,11 M -7,8 L 0,11 L 7,8" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="-4" r="1.5" fill="currentColor"/></g>
<g transform="translate(182, 0)"><path d="M 0,11 L 0,-5 M -6,-11 L -6,-3 L 0,-3 M 6,-11 L 6,-3 L 0,-3" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="5" x2="8" y2="5" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-8" r="1.4" fill="currentColor"/></g>
<g transform="translate(208, 0)"><path d="M 5,-10 A 11 11 0 0 0 5,10 M -4,-5 L 4,-5 M -6,0 L 2,0 M -4,5 L 4,5" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="-2" cy="-10" r="1.2" fill="currentColor"/></g>
</g>
  <g transform="translate(70, 100) scale(0.85)" color={c.patina1}>
<g transform="translate(0, 0)"><path d="M 5,-10 A 11 11 0 0 0 5,10 M -4,-5 L 4,-5 M -6,0 L 2,0 M -4,5 L 4,5" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="-2" cy="-10" r="1.2" fill="currentColor"/></g>
<g transform="translate(20, 0)"><path d="M -8,11 L -8,-4 L -4,-4 L -4,-10 L 4,-10 L 4,-4 L 8,-4 L 8,11" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="3" x2="8" y2="3" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-5" r="1.6" fill="currentColor"/></g>
<g transform="translate(40, 0)"><polygon points="0,-11 7,0 0,11 -7,0" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1"/>
       <circle cx="0" cy="0" r="2" fill="currentColor"/></g>
<g transform="translate(60, 0)"><path d="M -8,8 Q -2,-4 8,-10 L 2,10 Z" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-3" y1="1" x2="5" y2="1" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="-5" cy="-8" r="1.4" fill="currentColor"/></g>
<g transform="translate(80, 0)"><path d="M 0,-11 L 0,11 M -6,-3 L 0,-9 L 6,-3 M -4,4 L 0,8 L 4,4" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="-11" r="1.5" fill="currentColor"/></g>
<g transform="translate(100, 0)"><line x1="-8" y1="-8" x2="8" y2="-8" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="8" x2="8" y2="8" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-4" y1="-8" x2="4" y2="8" stroke="currentColor" strokeWidth="1.1"/>
       <line x1="4" y1="-8" x2="-4" y2="8" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="0" r="1.8" fill="currentColor"/></g>
<g transform="translate(120, 0)"><path d="M 0,11 L 0,-5 M -6,-11 L -6,-3 L 0,-3 M 6,-11 L 6,-3 L 0,-3" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="5" x2="8" y2="5" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-8" r="1.4" fill="currentColor"/></g>
<g transform="translate(140, 0)"><path d="M -8,-8 Q -4,0 -8,8 M -2,-10 Q 3,0 -2,10 M 4,-6 Q 8,0 4,6" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="8" cy="-8" r="1.3" fill="currentColor"/>
       <circle cx="8" cy="8" r="1.3" fill="currentColor"/></g>
<g transform="translate(160, 0)"><circle cx="0" cy="0" r="7" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="-9" y1="0" x2="9" y2="0" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="0" cy="-7" r="1.2" fill="currentColor"/>
       <circle cx="0" cy="7" r="1.2" fill="currentColor"/></g>
<g transform="translate(180, 0)"><path d="M -9,0 Q 0,-8 9,0 Q 0,8 -9,0 Z" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="0" r="3" fill="currentColor"/>
       <line x1="0" y1="-11" x2="0" y2="-6" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="6" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/></g>
<g transform="translate(200, 0)"><path d="M -7,-7 L 0,-1 L 7,-7 M -7,3 L 0,9 L 7,3" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-11" r="1.3" fill="currentColor"/></g>
</g>

  {/* Выноска к Расе Кормчих */}
  <path d="M 855 450 L 780 290 L 690 290" fill="none" stroke={c.copper2} strokeWidth="1" strokeOpacity="0.6" />
  <circle cx="855" cy="450" r="2.5" fill={c.copper2} />
  <g transform="translate(510, 288) scale(1.0)" color={c.copper2}>
<g transform="translate(0, 0)"><path d="M -9,0 Q 0,-8 9,0 Q 0,8 -9,0 Z" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="0" r="3" fill="currentColor"/>
       <line x1="0" y1="-11" x2="0" y2="-6" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="6" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/></g>
<g transform="translate(25, 0)"><circle cx="0" cy="0" r="7" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="-9" y1="0" x2="9" y2="0" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="0" cy="-7" r="1.2" fill="currentColor"/>
       <circle cx="0" cy="7" r="1.2" fill="currentColor"/></g>
<g transform="translate(50, 0)"><path d="M 0,-11 L 0,11 M -6,-3 L 0,-9 L 6,-3 M -4,4 L 0,8 L 4,4" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="-11" r="1.5" fill="currentColor"/></g>
<g transform="translate(75, 0)"><line x1="-8" y1="-8" x2="8" y2="-8" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="8" x2="8" y2="8" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-4" y1="-8" x2="4" y2="8" stroke="currentColor" strokeWidth="1.1"/>
       <line x1="4" y1="-8" x2="-4" y2="8" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="0" r="1.8" fill="currentColor"/></g>
<g transform="translate(100, 0)"><path d="M -7,-7 L 0,-1 L 7,-7 M -7,3 L 0,9 L 7,3" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-11" r="1.3" fill="currentColor"/></g>
<g transform="translate(125, 0)"><polygon points="0,-11 7,0 0,11 -7,0" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1"/>
       <circle cx="0" cy="0" r="2" fill="currentColor"/></g>
<g transform="translate(150, 0)"><circle cx="0" cy="-4" r="5" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <path d="M 0,1 L 0,11 M -7,8 L 0,11 L 7,8" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="-4" r="1.5" fill="currentColor"/></g>
</g>
  <g transform="translate(550, 312) scale(0.65)" color={c.copper2}>
<g transform="translate(0, 0)"><path d="M 5,-10 A 11 11 0 0 0 5,10 M -4,-5 L 4,-5 M -6,0 L 2,0 M -4,5 L 4,5" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="-2" cy="-10" r="1.2" fill="currentColor"/></g>
<g transform="translate(18, 0)"><path d="M 0,11 L 0,-5 M -6,-11 L -6,-3 L 0,-3 M 6,-11 L 6,-3 L 0,-3" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="5" x2="8" y2="5" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-8" r="1.4" fill="currentColor"/></g>
<g transform="translate(36, 0)"><path d="M -8,-8 Q -4,0 -8,8 M -2,-10 Q 3,0 -2,10 M 4,-6 Q 8,0 4,6" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="8" cy="-8" r="1.3" fill="currentColor"/>
       <circle cx="8" cy="8" r="1.3" fill="currentColor"/></g>
<g transform="translate(54, 0)"><path d="M -8,11 L -8,-4 L -4,-4 L -4,-10 L 4,-10 L 4,-4 L 8,-4 L 8,11" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="3" x2="8" y2="3" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-5" r="1.6" fill="currentColor"/></g>
</g>

  {/* Выноска к Резонирующему Монолиту */}
  <path d="M 1180 340 L 1230 205 L 1255 205" fill="none" stroke={c.patina2} strokeWidth="1" strokeOpacity="0.6" />
  <circle cx="1180" cy="340" r="2.5" fill={c.patina2} />
  <g transform="translate(1260, 205) scale(1.0)" color={c.patina2}>
<g transform="translate(0, 0)"><polygon points="0,-11 7,0 0,11 -7,0" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1"/>
       <circle cx="0" cy="0" r="2" fill="currentColor"/></g>
<g transform="translate(25, 0)"><path d="M -8,11 L -8,-4 L -4,-4 L -4,-10 L 4,-10 L 4,-4 L 8,-4 L 8,11" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="3" x2="8" y2="3" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-5" r="1.6" fill="currentColor"/></g>
<g transform="translate(50, 0)"><path d="M -8,-8 Q -4,0 -8,8 M -2,-10 Q 3,0 -2,10 M 4,-6 Q 8,0 4,6" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="8" cy="-8" r="1.3" fill="currentColor"/>
       <circle cx="8" cy="8" r="1.3" fill="currentColor"/></g>
<g transform="translate(75, 0)"><path d="M 0,-11 L 0,11 M -6,-3 L 0,-9 L 6,-3 M -4,4 L 0,8 L 4,4" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="-11" r="1.5" fill="currentColor"/></g>
<g transform="translate(100, 0)"><circle cx="0" cy="0" r="7" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="-9" y1="0" x2="9" y2="0" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="0" cy="-7" r="1.2" fill="currentColor"/>
       <circle cx="0" cy="7" r="1.2" fill="currentColor"/></g>
<g transform="translate(125, 0)"><circle cx="0" cy="-4" r="5" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <path d="M 0,1 L 0,11 M -7,8 L 0,11 L 7,8" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="-4" r="1.5" fill="currentColor"/></g>
<g transform="translate(150, 0)"><path d="M -9,0 Q 0,-8 9,0 Q 0,8 -9,0 Z" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="0" r="3" fill="currentColor"/>
       <line x1="0" y1="-11" x2="0" y2="-6" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="6" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/></g>
<g transform="translate(175, 0)"><path d="M 5,-10 A 11 11 0 0 0 5,10 M -4,-5 L 4,-5 M -6,0 L 2,0 M -4,5 L 4,5" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="-2" cy="-10" r="1.2" fill="currentColor"/></g>
</g>
  <g transform="translate(1310, 228) scale(0.65)" color={c.patina1}>
<g transform="translate(0, 0)"><path d="M -7,-7 L 0,-1 L 7,-7 M -7,3 L 0,9 L 7,3" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-11" r="1.3" fill="currentColor"/></g>
<g transform="translate(18, 0)"><path d="M -8,8 Q -2,-4 8,-10 L 2,10 Z" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-3" y1="1" x2="5" y2="1" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="-5" cy="-8" r="1.4" fill="currentColor"/></g>
<g transform="translate(36, 0)"><polygon points="0,-11 7,0 0,11 -7,0" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1"/>
       <circle cx="0" cy="0" r="2" fill="currentColor"/></g>
<g transform="translate(54, 0)"><path d="M 0,11 L 0,-5 M -6,-11 L -6,-3 L 0,-3 M 6,-11 L 6,-3 L 0,-3" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="5" x2="8" y2="5" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-8" r="1.4" fill="currentColor"/></g>
</g>

  {/* Выноска к Деревушке людей у подножия */}
  <path d="M 1075 700 L 1000 805 L 870 805" fill="none" stroke={c.ink} strokeWidth="1" strokeOpacity="0.5" />
  <circle cx="1075" cy="700" r="2.5" fill={c.ink} />
  <g transform="translate(690, 805) scale(1.0)" color={c.ink}>
<g transform="translate(0, 0)"><path d="M -8,11 L -8,-4 L -4,-4 L -4,-10 L 4,-10 L 4,-4 L 8,-4 L 8,11" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="3" x2="8" y2="3" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-5" r="1.6" fill="currentColor"/></g>
<g transform="translate(25, 0)"><path d="M 5,-10 A 11 11 0 0 0 5,10 M -4,-5 L 4,-5 M -6,0 L 2,0 M -4,5 L 4,5" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="-2" cy="-10" r="1.2" fill="currentColor"/></g>
<g transform="translate(50, 0)"><path d="M 0,11 L 0,-5 M -6,-11 L -6,-3 L 0,-3 M 6,-11 L 6,-3 L 0,-3" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="5" x2="8" y2="5" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-8" r="1.4" fill="currentColor"/></g>
<g transform="translate(75, 0)"><line x1="-8" y1="-8" x2="8" y2="-8" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-8" y1="8" x2="8" y2="8" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="-4" y1="-8" x2="4" y2="8" stroke="currentColor" strokeWidth="1.1"/>
       <line x1="4" y1="-8" x2="-4" y2="8" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="0" r="1.8" fill="currentColor"/></g>
<g transform="translate(100, 0)"><path d="M -8,-8 Q -4,0 -8,8 M -2,-10 Q 3,0 -2,10 M 4,-6 Q 8,0 4,6" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="8" cy="-8" r="1.3" fill="currentColor"/>
       <circle cx="8" cy="8" r="1.3" fill="currentColor"/></g>
<g transform="translate(125, 0)"><path d="M 0,-11 L 0,11 M -6,-3 L 0,-9 L 6,-3 M -4,4 L 0,8 L 4,4" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="-11" r="1.5" fill="currentColor"/></g>
<g transform="translate(150, 0)"><path d="M -7,-7 L 0,-1 L 7,-7 M -7,3 L 0,9 L 7,3" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.1"/>
       <circle cx="0" cy="-11" r="1.3" fill="currentColor"/></g>
</g>
  <g transform="translate(740, 826) scale(0.65)" color={c.muted}>
<g transform="translate(0, 0)"><circle cx="0" cy="0" r="7" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="-9" y1="0" x2="9" y2="0" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="0" cy="-7" r="1.2" fill="currentColor"/>
       <circle cx="0" cy="7" r="1.2" fill="currentColor"/></g>
<g transform="translate(18, 0)"><path d="M -9,0 Q 0,-8 9,0 Q 0,8 -9,0 Z" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="0" r="3" fill="currentColor"/>
       <line x1="0" y1="-11" x2="0" y2="-6" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="6" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/></g>
<g transform="translate(36, 0)"><polygon points="0,-11 7,0 0,11 -7,0" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1"/>
       <circle cx="0" cy="0" r="2" fill="currentColor"/></g>
</g>

  {/* Иероглифическая шкала внизу */}
  <g transform="translate(70, 830)">
    <line x1="0" y1="0" x2="200" y2="0" stroke={c.ink} strokeWidth="1.2" strokeOpacity="0.6" />
    <line x1="0" y1="-5" x2="0" y2="5" stroke={c.ink} strokeWidth="1.2" strokeOpacity="0.6" />
    <line x1="100" y1="-3" x2="100" y2="3" stroke={c.ink} strokeWidth="1" strokeOpacity="0.4" />
    <line x1="200" y1="-5" x2="200" y2="5" stroke={c.ink} strokeWidth="1.2" strokeOpacity="0.6" />
    {/* Глифы чисел Кормчих под делениями шкалы */}
    <g transform="translate(0, 16) scale(0.6)" color={c.muted}>
      <path d="M 0,-11 L 0,11 M -6,-3 L 0,-9 L 6,-3 M -4,4 L 0,8 L 4,4" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="0" cy="-11" r="1.5" fill="currentColor"/>
    </g>
    <g transform="translate(95, 16) scale(0.6)" color={c.muted}>
      <circle cx="0" cy="0" r="7" fill="none" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="0" y1="-11" x2="0" y2="11" stroke="currentColor" strokeWidth="1.2"/>
       <line x1="-9" y1="0" x2="9" y2="0" stroke="currentColor" strokeWidth="1.2"/>
       <circle cx="0" cy="-7" r="1.2" fill="currentColor"/>
       <circle cx="0" cy="7" r="1.2" fill="currentColor"/>
    </g>
    <g transform="translate(195, 16) scale(0.6)" color={c.muted}>
      <path d="M -8,-8 Q -4,0 -8,8 M -2,-10 Q 3,0 -2,10 M 4,-6 Q 8,0 4,6" fill="none" stroke="currentColor" strokeWidth="1.3"/>
       <circle cx="8" cy="-8" r="1.3" fill="currentColor"/>
       <circle cx="8" cy="8" r="1.3" fill="currentColor"/>
    </g>
  </g>
</svg>
  );
}
