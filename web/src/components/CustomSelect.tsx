import { useEffect, useRef, useState, type ReactNode } from "react";

export interface SelectOption<T extends string = string> {
  value: T;
  label: string;
  sublabel?: string;
  badge?: string;
  badgeTone?: "accent" | "patina" | "ember" | "muted";
  icon?: ReactNode;
}

export type OptionItem<T extends string = string> = SelectOption<T> | [T, string];

function normalizeOption<T extends string>(opt: OptionItem<T>): SelectOption<T> {
  if (Array.isArray(opt)) {
    return { value: opt[0], label: opt[1] };
  }
  return opt;
}

interface CustomSelectProps<T extends string = string> {
  value: T;
  options: OptionItem<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  placeholder?: string;
  className?: string;
  buttonClassName?: string;
  ariaLabel?: string;
  title?: string;
  size?: "sm" | "md";
}

/**
 * Атмосферный выпадающий список в стиле TaleForge («Судовой журнал»):
 * графитовые панели, латунная/медная обводка, плавный шеврон, подсветка и бейджи.
 */
export default function CustomSelect<T extends string = string>({
  value,
  options,
  onChange,
  disabled = false,
  placeholder = "Выберите...",
  className = "",
  buttonClassName = "",
  ariaLabel,
  title,
  size = "md",
}: CustomSelectProps<T>) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const listboxRef = useRef<HTMLDivElement>(null);

  const normalized = options.map(normalizeOption);
  const selected = normalized.find((o) => o.value === value);

  // Close on outside click
  useEffect(() => {
    if (!isOpen) return;

    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  const py = size === "sm" ? "py-1.5" : "py-2";
  const px = size === "sm" ? "px-3" : "px-3.5";
  const textSize = size === "sm" ? "text-xs" : "text-sm";

  return (
    <div
      ref={containerRef}
      className={`relative inline-block w-full ${className}`}
      title={title}
    >
      {/* Trigger Button */}
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-label={ariaLabel}
        onClick={() => !disabled && setIsOpen((prev) => !prev)}
        className={`group flex w-full items-center justify-between gap-2.5 rounded-[10px] border bg-bg ${px} ${py} ${textSize} transition text-left ${
          isOpen
            ? "border-accent ring-1 ring-accent/30 shadow-[0_0_12px_rgba(201,138,75,0.15)]"
            : "border-line hover:border-accent/70"
        } ${
          disabled
            ? "cursor-not-allowed opacity-50 bg-raised/50"
            : "cursor-pointer"
        } ${buttonClassName}`}
      >
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {selected?.icon && <span className="shrink-0">{selected.icon}</span>}
          <span className={`truncate font-medium ${selected ? "text-ink" : "text-muted"}`}>
            {selected ? selected.label : placeholder}
          </span>
          {selected?.badge && (
            <span
              className={`shrink-0 rounded-[6px] px-1.5 py-0.2 font-mono text-[10px] font-semibold uppercase tracking-wider ${
                selected.badgeTone === "accent"
                  ? "bg-accent/20 text-accent border border-accent/40"
                  : selected.badgeTone === "patina"
                    ? "bg-patina/20 text-patina-hi border border-patina/40"
                    : selected.badgeTone === "ember"
                      ? "bg-bad/20 text-bad border border-bad/40"
                      : "bg-raised text-muted border border-line"
              }`}
            >
              {selected.badge}
            </span>
          )}
        </div>

        {/* Custom Copper Chevron */}
        <span
          className={`shrink-0 text-accent transition-transform duration-200 ${
            isOpen ? "rotate-180" : ""
          }`}
          aria-hidden="true"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </span>
      </button>

      {/* Dropdown Floating Menu */}
      {isOpen && (
        <div
          ref={listboxRef}
          role="listbox"
          aria-label={ariaLabel}
          className="absolute left-0 right-0 top-full z-50 mt-1.5 max-h-64 overflow-y-auto rounded-[12px] border border-accent/40 bg-surface p-1.5 shadow-[0_12px_32px_rgba(0,0,0,0.5)] backdrop-blur-md animate-in fade-in zoom-in-95 duration-100"
        >
          <div className="flex flex-col gap-1">
            {normalized.map((opt) => {
              const isSelected = opt.value === value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => {
                    onChange(opt.value);
                    setIsOpen(false);
                  }}
                  className={`group flex w-full items-center justify-between gap-3 rounded-[8px] px-3 py-2 text-left transition ${
                    isSelected
                      ? "bg-accent/15 text-accent font-semibold"
                      : "text-ink hover:bg-raised/90 hover:text-accent-hi"
                  }`}
                >
                  <div className="flex min-w-0 flex-1 flex-col">
                    <div className="flex items-center gap-2">
                      {opt.icon && <span className="shrink-0">{opt.icon}</span>}
                      <span className="truncate text-xs sm:text-sm">{opt.label}</span>
                      {opt.badge && (
                        <span
                          className={`shrink-0 rounded-[5px] px-1.5 py-0.2 font-mono text-[9px] font-semibold uppercase ${
                            opt.badgeTone === "accent"
                              ? "bg-accent/20 text-accent"
                              : opt.badgeTone === "patina"
                                ? "bg-patina/20 text-patina-hi"
                                : opt.badgeTone === "ember"
                                  ? "bg-bad/20 text-bad"
                                  : "bg-raised text-muted"
                          }`}
                        >
                          {opt.badge}
                        </span>
                      )}
                    </div>
                    {opt.sublabel && (
                      <span
                        className={`text-[11px] truncate mt-0.5 ${
                          isSelected ? "text-accent/80" : "text-muted group-hover:text-ink-2"
                        }`}
                      >
                        {opt.sublabel}
                      </span>
                    )}
                  </div>

                  {isSelected && (
                    <span className="shrink-0 text-accent font-bold" aria-hidden="true">
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
