import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const alertVariants = cva('relative w-full rounded-lg border p-4 text-sm [&_svg]:size-5 flex gap-3', {
  variants: {
    variant: {
      info: 'border-border bg-muted text-foreground',
      warning: 'border-amber-brand bg-amber-brand/15 text-foreground',
      error: 'border-danger bg-danger/10 text-foreground',
      success: 'border-teal bg-teal/10 text-foreground',
    },
  },
  defaultVariants: { variant: 'info' },
});

export const Alert = ({
  className,
  variant,
  ...p
}: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>) => (
  <div className={cn(alertVariants({ variant }), className)} {...p} />
);
export const AlertTitle = ({ className, ...p }: React.HTMLAttributes<HTMLParagraphElement>) => (
  <p className={cn('font-semibold', className)} {...p} />
);
