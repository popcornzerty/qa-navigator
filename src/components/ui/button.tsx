import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:opacity-45 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-foreground hover:bg-primary/90",
        subtle: "bg-primary/10 text-primary ring-1 ring-primary/30 hover:bg-primary/20",
        outline: "ring-1 ring-line text-muted-foreground hover:text-foreground hover:bg-panel2",
        ghost: "text-muted-foreground hover:text-foreground hover:bg-panel2",
        danger: "bg-destructive/10 text-destructive ring-1 ring-destructive/30 hover:bg-destructive/20",
      },
      size: {
        sm: "text-xs px-3 py-1.5",
        md: "text-sm px-3.5 py-2",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export function Button({
  className,
  variant,
  size,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
