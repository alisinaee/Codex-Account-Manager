import React from "react";

const variantClassByName = {
  primary: "btn-primary",
  secondary: "btn-secondary",
  danger: "btn-danger",
  dangerOutline: "btn-danger-outline",
  ghost: "btn-ghost",
  icon: "btn-icon",
  warning: "btn-warning",
};

function Button({
  children,
  variant = "secondary",
  loading = false,
  disabled = false,
  disabledReason = "",
  className = "",
  type = "button",
  ...props
}) {
  const variantClass = variantClassByName[variant] || "";
  const classes = [
    "btn",
    variantClass,
    loading ? "btn-progress" : "",
    className,
  ].filter(Boolean).join(" ");
  const title = disabled && disabledReason ? disabledReason : props.title;

  return (
    <button
      {...props}
      type={type}
      className={classes}
      disabled={disabled || loading}
      title={title}
    >
      {children}
    </button>
  );
}

export default Button;
