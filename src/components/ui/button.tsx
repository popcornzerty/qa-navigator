import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:opacity-45 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        primary: "bg-primary text-primary-foreground hover:bg-primary/90",
        subtle: "bg-primary/10 text-primary ring-1 ring-primary/30 hover:bg-primary/20",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        outline: "ring-1 ring-line text-muted-foreground hover:text-foreground hover:bg-panel2",
        ghost: "text-muted-foreground hover:text-foreground hover:bg-panel2",
        link: "text-primary underline-offset-4 hover:underline",
        danger:
          "bg-destructive/10 text-destructive ring-1 ring-destructive/30 hover:bg-destructive/20",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
      },
      size: {
        default: "text-sm px-3.5 py-2",
        md: "text-sm px-3.5 py-2",
        sm: "text-xs px-3 py-1.5",
        lg: "text-sm px-5 py-2.5",
        icon: "size-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
