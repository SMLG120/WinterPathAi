import { m, useReducedMotion } from 'motion/react';
import { cn } from '@/lib/utils';

/** Section with a subtle fade-in (disabled under prefers-reduced-motion via MotionConfig). */
export function Section({
  id,
  title,
  intro,
  children,
  className,
  titleId,
}: {
  id?: string;
  title?: string;
  intro?: string;
  children: React.ReactNode;
  className?: string;
  titleId?: string;
}) {
  const hid = titleId ?? (id ? `${id}-title` : undefined);
  // ux-spec: all animation disabled under prefers-reduced-motion (Motion's "user" mode only drops transforms).
  const reduce = useReducedMotion();
  return (
    <m.section
      id={id}
      aria-labelledby={title ? hid : undefined}
      className={cn('mx-auto max-w-6xl scroll-mt-20 px-4 py-14', className)}
      initial={reduce ? false : { opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-60px' }}
      transition={{ duration: 0.45, ease: 'easeOut' }}
    >
      {title && (
        <h2 id={hid} className="font-serif text-2xl font-semibold sm:text-3xl">
          {title}
        </h2>
      )}
      {intro && <p className="mt-2 max-w-3xl text-muted-foreground">{intro}</p>}
      <div className={title || intro ? 'mt-8' : undefined}>{children}</div>
    </m.section>
  );
}

export function PageHeader({ title, intro, children }: { title: string; intro?: string; children?: React.ReactNode }) {
  return (
    <div className="border-b border-border bg-card">
      <div className="mx-auto max-w-6xl px-4 py-10">
        <h1 className="font-serif text-3xl font-semibold sm:text-4xl">{title}</h1>
        {intro && <p className="mt-3 max-w-3xl text-lg text-muted-foreground">{intro}</p>}
        {children && <div className="mt-4 flex flex-wrap items-center gap-2">{children}</div>}
      </div>
    </div>
  );
}
