import type { ElementType, HTMLAttributes } from "react";

type PageContainerProps = HTMLAttributes<HTMLElement> & {
  /** Rendered element; defaults to a plain `div`. */
  as?: ElementType;
};

/** Centers content at the shared maximum width with fluid side gutters. */
export function PageContainer({ as: Component = "div", className, ...rest }: PageContainerProps) {
  const classes = className ? `container-page ${className}` : "container-page";
  return <Component className={classes} {...rest} />;
}
