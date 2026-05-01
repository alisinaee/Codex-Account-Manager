import React from "react";

const variantClassByName = {
  success: "chip-success",
  warning: "chip-warning",
  danger: "chip-danger",
  neutral: "chip-neutral",
};

function Badge({ children, variant = "neutral", className = "", ...props }) {
  const variantClass = variantClassByName[variant] || variantClassByName.neutral;
  return (
    <span {...props} className={["chip", variantClass, className].filter(Boolean).join(" ")}>
      {children}
    </span>
  );
}

export default Badge;
