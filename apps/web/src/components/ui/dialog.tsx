import * as React from 'react';
import * as D from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

export function DialogContent({
  className,
  children,
  closeLabel,
  ...p
}: React.ComponentProps<typeof D.Content> & { closeLabel: string }) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-navy/60" />
      <D.Content
        className={cn(
          'fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-card p-6 text-card-foreground shadow-xl',
          className,
        )}
        {...p}
      >
        {children}
        <D.Close
          className="absolute right-3 top-3 inline-flex size-8 items-center justify-center rounded-md hover:bg-muted"
          aria-label={closeLabel}
        >
          <X className="size-4" aria-hidden="true" />
        </D.Close>
      </D.Content>
    </D.Portal>
  );
}
export const DialogTitle = ({ className, ...p }: React.ComponentProps<typeof D.Title>) => (
  <D.Title className={cn('text-lg font-semibold', className)} {...p} />
);
export const DialogDescription = ({ className, ...p }: React.ComponentProps<typeof D.Description>) => (
  <D.Description className={cn('mt-2 text-sm text-muted-foreground', className)} {...p} />
);
